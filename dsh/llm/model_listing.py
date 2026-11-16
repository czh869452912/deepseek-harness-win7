"""Pinned DeepSeek /models decoding and an owned, redirect-refusing HTTP read."""
import asyncio
from bisect import bisect_right
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import urllib.request
import zlib

from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.cordis.utils import js_to_string
from dsh.core.timeout import timeout_of
from dsh.host.http_proxy_policy import JS_SPACE, parse_url
from dsh.llm.attribution import attribution_headers
from dsh.llm.http_stream import open_stream
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_json import loads
from dsh.terminal.grapheme import segments

PRODUCT = 'deepseek-harness'
MAX_BADGE_TEXT_LENGTH = 12
LISTING_TIMEOUT = 'MODEL_LISTING_TIMEOUT'
class InvalidListingURL(ValueError):
    code = 'ERR_INVALID_URL'


def modelListingURL(baseURL):
    parsed = parse_url(baseURL)
    if parsed is None or parsed['protocol'] not in ('http:', 'https:', 'ws:', 'wss:', 'ftp:'):
        raise InvalidListingURL('Invalid URL')
    host = parsed['hostname']
    if ':' in host: host = '['+host+']'
    defaults = {'http:':80, 'https:':443, 'ws:':80, 'wss:':443, 'ftp:':21}
    port = '' if parsed['port'] in (None, defaults[parsed['protocol']]) else ':'+str(parsed['port'])
    return parsed['protocol']+'//'+host+port+'/models'


@lru_cache(maxsize=1)
def _tables():
    data = json.loads((Path(__file__).resolve().parents[1]/'resources/model_badge_unicode16.json').read_text(encoding='utf-8'))
    return {key: ([row[0] for row in rows], rows) for key, rows in data['tables'].items()}


def _has_property(code, key):
    starts, rows = _tables()[key]
    index = bisect_right(starts, code)-1
    return index >= 0 and code <= rows[index][1]


def _badge_text(value):
    if not isinstance(value, str): return None
    text = value.strip(JS_SPACE)
    if (len(segments(text)) <= MAX_BADGE_TEXT_LENGTH
            and any(not _has_property(ord(char), 'invisible') for char in text)
            and not any(_has_property(ord(char), 'unreadable') for char in value)):
        return text
    return None


def _localized_text(value):
    if isinstance(value, str): return _badge_text(value)
    if not isinstance(value, dict): return None
    texts = {}
    for language, variant in value.items():
        text = _badge_text(variant)
        if re.fullmatch(r'[a-z]{2,8}(?:-[a-z0-9]{1,8})*', language) is None or text is None: return None
        texts[language] = text
    return texts if 'en' in texts else None


def _badge(entry):
    own_name = 'client_metadata["'+PRODUCT+'"]'
    current = entry
    for key, diagnostic in [('client_metadata', 'client_metadata'), (PRODUCT, own_name), ('badge', own_name+'.badge')]:
        current = current.get(key)
        if current is None: return None
        if not isinstance(current, dict): return dict(kind='invalid', reason=diagnostic+' is not an object')
    text = _localized_text(current.get('text'))
    if text is None:
        return dict(kind='invalid', reason=own_name+'.badge.text is not a string or an object of lowercase language ids including "en", '
            +'each text 1 to '+str(MAX_BADGE_TEXT_LENGTH)+' characters on one line')
    tone = current.get('tone')
    return dict(kind='badge', badge=dict(text=text, tone=tone if tone in ('neutral', 'info', 'success', 'warning') else 'neutral'))


def _requirement(entry):
    if 'client_requirements' not in entry: return dict(kind='none')
    requirements = entry['client_requirements']
    if not isinstance(requirements, dict): return dict(kind='invalid')
    if PRODUCT not in requirements: return dict(kind='none')
    own = requirements[PRODUCT]
    if not isinstance(own, dict): return dict(kind='invalid')
    if 'min_version' not in own: return dict(kind='none')
    version = own['min_version']
    return dict(kind='min-version', version=version) if isinstance(version, str) and version else dict(kind='invalid')


def _modalities(entry, key):
    if key not in entry: return ['text']
    value = entry[key]
    if not isinstance(value, list): return None
    return sorted([item for item in ('text', 'image') if item in value], key=value.index)


def _capacity(value):
    return type(value) in (int, float) and 0 < value <= 9007199254740991 and math.isfinite(value) and int(value) == value


def _capabilities(entry):
    capabilities = entry.get('api_capabilities')
    messages = capabilities.get('anthropic_messages') if isinstance(capabilities, dict) else None
    if not isinstance(messages, dict): return dict(usable=False, reason='declares no api_capabilities.anthropic_messages')
    outputs, inputs = _modalities(entry, 'output_modalities'), _modalities(entry, 'input_modalities')
    if outputs is None or 'text' not in outputs: return dict(usable=False, reason='declares no text output')
    if not inputs: return dict(usable=False, reason='declares no input modality DeepSeek Harness supports')
    facts = dict(inputModalities=inputs)
    for key, target in [('context_window', 'contextWindow'), ('max_output_tokens', 'maxOutputTokens')]:
        if key not in entry: continue
        if not _capacity(entry[key]): return dict(usable=False, reason='declares an invalid context_window or max_output_tokens')
        facts[target] = entry[key]
    for key, target, accepted in [('system_prompt_update', 'systemPromptUpdate', ('in-history',)),
                                  ('tool_update', 'toolUpdate', ('in-history', 'addition-only'))]:
        value = messages.get(key)
        if value is not None: facts[target] = value if value in accepted else 'leading-only'
    return dict(usable=True, facts=facts)


def parseModelListing(body):
    data = body.get('data') if isinstance(body, dict) else None
    if not isinstance(data, list): raise LlmError('DeepSeek model listing has no "data" array', 'INVALID_RESPONSE')
    entries, seen = [], set()
    for row in data:
        if not isinstance(row, dict): continue
        model_id = row.get('id')
        if not isinstance(model_id, str) or not model_id or model_id in seen: continue
        seen.add(model_id)
        entry = dict(id=model_id, requirement=_requirement(row), capabilities=_capabilities(row))
        if isinstance(row.get('name'), str) and row['name']: entry['name'] = row['name']
        badge = _badge(row)
        if badge is not None: entry['badge'] = badge
        entries.append(entry)
    if not entries: raise LlmError('DeepSeek model listing contains no model entry', 'INVALID_RESPONSE')
    return dict(entries=entries, skipped=len(data)-len(entries))


def _decompress(payload, window):
    # Fetch's zlib streams use Z_SYNC_FLUSH at finish: a missing gzip trailer
    # does not discard a fully decoded body. Still validate present checksums.
    result = []
    while payload:
        decoder = zlib.decompressobj(window)
        result.append(decoder.decompress(payload)+decoder.flush())
        payload = decoder.unused_data
        if window != 16+zlib.MAX_WBITS or payload.startswith(b'\0'): break
    return b''.join(result)


async def requestModelListing(url, headers, signal=NEVER_ABORTED):
    operation = AbortController()
    detach = signal.add_listener('abort', lambda *_: operation.abort(signal.reason))
    def read():
        try:
            declared = {key.lower(): value for key, value in attribution_headers().items()}
            declared['accept'] = 'application/json'
            declared.update(headers)
            merged = {}
            for key, value in declared.items():
                key = key.lower()
                merged[key] = merged[key]+', '+value if key in merged else value
            request = urllib.request.Request(url, headers=merged, method='GET')
            with open_stream(request, operation.signal, idle_timeout_ms=2147483647,
                             redirect_policy='error', raise_http_errors=False) as (response, chunks):
                status = response.status
                payload = b''.join(chunks)
                for encoding in reversed(response.headers.get('content-encoding', '').split(',')):
                    encoding = encoding.strip().lower()
                    if encoding == 'gzip': payload = _decompress(payload, 16+zlib.MAX_WBITS)
                    elif encoding == 'deflate':
                        payload = _decompress(payload, zlib.MAX_WBITS if payload and payload[0]&15 == 8 else -zlib.MAX_WBITS)
                text = payload.decode('utf-8-sig', errors='replace')
        except Exception as error:
            expired = timeout_of(signal, LISTING_TIMEOUT)
            if expired is not None:
                raise LlmError('DeepSeek model listing request to '+url+' timed out after '+js_to_string(expired.timeoutMs)+' ms', 'TIMEOUT') from error
            if operation.signal.aborted:
                raise LlmError('DeepSeek model listing request to '+url+' was aborted', 'ABORTED') from error
            raise LlmError('could not reach '+url, 'TRANSPORT') from error
        if not 200 <= status < 300: raise LlmError(url+' answered HTTP '+str(status), 'HTTP_'+str(status), status=status)
        try: body = loads(text)
        except Exception as error: raise LlmError(url+' did not answer with JSON', 'INVALID_RESPONSE') from error
        return parseModelListing(body)
    worker = asyncio.get_running_loop().run_in_executor(None, read)
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        operation.abort()
        try: await asyncio.shield(worker)
        except Exception: pass
        raise
    finally:
        detach()
