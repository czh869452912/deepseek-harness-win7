"""Bounded anonymous HTTP fetch, with presentation owned by tool-web."""
import json
import math
from pathlib import Path
from urllib.parse import urljoin

from dsh.cordis.plugin import Plugin
from dsh.cordis.awaiting import start_coroutine
from dsh.core.cancellation import aborted
from dsh.core.timeout import deadline, timeout_of, _number_text
from dsh.host.http_request import request as requestHttp
from dsh.web.fetch_policy_current import validateFetchUrl, isSameOrigin, classifyContentType, parseCharset, decoderForCharset
from dsh.web.web_service import WebError
from dsh.cordis.schema import Schema


DEFAULTS = dict(maxResponseBytes=5000000, maxBodyChars=100000, timeoutMs=30000, maxRedirects=5,
                userAgent='deepseek-harness/0.0.1 (+https://github.com/deepseek-ai)')
Config = Schema.object({key: (Schema.string() if isinstance(value, str) else Schema.number()).default(value)
                        for key, value in DEFAULTS.items()})


def validateLimits(limits):
    for key in ('maxResponseBytes', 'maxBodyChars', 'timeoutMs'):
        value = limits[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError('web-fetch-http: '+key+' must be a positive finite number')
    if limits['timeoutMs'] > 2147483647:
        raise ValueError('web-fetch-http: timeoutMs must be no greater than 2147483647')
    value = limits['maxRedirects']
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0 or int(value) != value:
        raise ValueError('web-fetch-http: maxRedirects must be a non-negative integer')


def translateAbortOrNetwork(error, signal, phase):
    reason = timeout_of(signal, 'WEB_FETCH_TIMEOUT')
    if reason is not None: return WebError('web fetch timed out', 'WEB_FETCH_TIMEOUT', cause=reason)
    if aborted(signal): return WebError('web fetch aborted', 'WEB_ABORTED', cause=error)
    # Fetch presents platform/socket/parser failures through these stable wrappers.
    failure = TypeError('fetch failed' if phase == 'request' else 'terminated')
    failure.__cause__ = error
    return WebError('web fetch failed: TypeError: '+str(failure), 'WEB_PROVIDER_ERROR', cause=failure)


def resolveRedirect(location, base):
    try:
        text = location.strip(''.join(chr(index) for index in range(33))).replace('\t', '').replace('\r', '').replace('\n', '')
        # HTTP URLs treat backslashes as path/authority separators.
        target = urljoin(base['href'], text.replace('\\', '/'))
        from dsh.host.url_current import _url
        parsed = _url(target)
        return target if parsed['credentials'] else parsed['href']
    except (ValueError, TypeError) as error:
        raise WebError('invalid redirect Location "'+location+'"', 'WEB_PROVIDER_ERROR', cause=error)


class HttpFetchProvider:
    id = 'http'
    with (Path(__file__).resolve().parents[1]/'resources/web_http_description_022.json').open(encoding='utf-8') as _stream:
        description = json.load(_stream)

    def __init__(self, limits):
        self.limits = limits

    def available(self): return True

    def fetch(self, request, signal=None):
        return start_coroutine(self._fetch(request, signal))

    async def _fetch(self, request, signal=None):
        if aborted(signal): raise WebError('web fetch aborted', 'WEB_ABORTED')
        with deadline(signal, self.limits['timeoutMs'], 'WEB_FETCH_TIMEOUT') as scoped:
            return await self.followAndRead(request['url'], scoped.signal)

    async def followAndRead(self, initialUrl, signal):
        current = validateFetchUrl(initialUrl); followed = 0
        while True:
            headers = {'user-agent': self.limits['userAgent'],
                       'accept': 'text/html,application/xhtml+xml,text/*;q=0.9,application/json;q=0.8'}
            manager = requestHttp(current['href'], 'GET', headers, None, signal, redirect_policy='manual', advertise_zstd=True)
            try: response, stream = await manager.__aenter__()
            except Exception as error: raise translateAbortOrNetwork(error, signal, 'request')
            try:
                status = response['status']; received = response['headers']
                if status in (301, 302, 303, 307, 308):
                    if followed >= self.limits['maxRedirects']:
                        raise WebError('exceeded the maximum of '+_number_text(self.limits['maxRedirects'])+' redirects', 'WEB_REDIRECT_BLOCKED')
                    location = received.get('location')
                    if location is None:
                        raise WebError('redirect response (HTTP '+str(status)+') without a Location header', 'WEB_PROVIDER_ERROR')
                    target = validateFetchUrl(resolveRedirect(location, current))
                    if not isSameOrigin(target, current):
                        raise WebError('cross-origin redirect to '+target['origin']+' is not followed automatically; retry against that URL directly', 'WEB_REDIRECT_BLOCKED')
                    current = target; followed += 1
                    continue
                return await self.readBody(response, stream, current, signal)
            finally:
                await manager.__aexit__(None, None, None)

    async def readBody(self, response, stream, finalUrl, signal):
        contentType = response['headers'].get('content-type')
        kind = classifyContentType(contentType)
        if kind is None:
            raise WebError('unsupported content type "'+('unknown' if contentType is None else contentType)+'"', 'WEB_UNSUPPORTED_CONTENT_TYPE')
        decoder = decoderForCharset(parseCharset(contentType))
        declared = response['headers'].get('content-length')
        if declared is not None:
            try: length = float(declared) if declared.strip() else 0
            except ValueError: length = float('nan')
            if math.isfinite(length) and length > self.limits['maxResponseBytes']:
                raise WebError('response exceeds the maximum of '+_number_text(self.limits['maxResponseBytes'])+' bytes', 'WEB_FETCH_TOO_LARGE')
        chunks = []; total = 0; truncated = False
        if response['hasBody']:
            try:
                async for value in stream:
                    remaining = self.limits['maxResponseBytes']-total
                    if len(value) > remaining:
                        chunks.append(value[:int(remaining)]); truncated = True
                        break
                    chunks.append(value); total += len(value)
            except Exception as error: raise translateAbortOrNetwork(error, signal, 'body')
        try: decoded = decoder.decode(b''.join(chunks), stream=decoder.fatal and truncated)
        except UnicodeError as error:
            raise WebError('response body is not valid UTF-8 for the malformed charset declaration', 'WEB_UNSUPPORTED_CONTENT_TYPE', cause=error)
        encoded = decoded.encode('utf-16-le', 'surrogatepass')
        charTruncated = len(encoded)//2 > self.limits['maxBodyChars']
        if charTruncated: decoded = encoded[:int(self.limits['maxBodyChars'])*2].decode('utf-16-le', 'surrogatepass')
        return dict(url=finalUrl['href'], statusCode=response['status'], body=dict(kind=kind, content=decoded), truncated=truncated or charTruncated)


class CurrentWebFetchHttp(Plugin):
    id = '@deepseek-ai/dsh-web-fetch-http'
    inject = ['web']
    Config = Config

    def apply(self, ctx):
        validateLimits(self.config)
        provider = HttpFetchProvider(dict(self.config))
        ctx.effect(lambda: ctx.web.registerFetchProvider(provider))
