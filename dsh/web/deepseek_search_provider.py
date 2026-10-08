"""Native Messages search, matching pinned web-search-deepseek/src/provider.ts."""
import asyncio
import inspect
import json
import urllib.parse
import urllib.request

from dsh.cordis.json_text import stringify_json
from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.llm.http_stream import open_stream
from dsh.web.web_service import WebError, WebSearchProvider

DEEPSEEK_PROVIDER_ID = 'deepseek-official'
DEEPSEEK_DEFAULT_BASE_URL = 'https://api.deepseek.com/anthropic/v1'
DEEPSEEK_DEFAULT_MODEL = 'deepseek-v4-flash'
DEEPSEEK_DEFAULT_API_VERSION = '2023-06-01'
DEEPSEEK_DEFAULT_MAX_TOKENS = 4096
DEEPSEEK_DEFAULT_MAX_USES = 5


def search_aborted(signal, fallback=None):
    return WebError('DeepSeek search aborted', 'WEB_ABORTED',
                    cause=getattr(signal, 'reason', None) if aborted(signal) else fallback)


def throw_if_search_aborted(signal):
    if aborted(signal):
        raise search_aborted(signal)


def error_text(error):
    name = getattr(error, 'name', 'TypeError' if isinstance(error, TypeError) else 'Error')
    message = getattr(error, 'message', str(error))
    return name + (': ' + message if message else '')


async def abortable(operation, signal):
    """Keep observing late credential settlement after the caller aborts."""
    if not inspect.isawaitable(operation):
        return operation
    task = asyncio.ensure_future(operation)
    if signal is None:
        return await task
    result = asyncio.get_running_loop().create_future()

    def settle(future):
        try:
            value = future.result()
        except BaseException as error:
            if not result.done():
                rendered = error_text(error)
                detail = rendered[7:] if rendered.startswith('Error: ') else rendered
                wrapped = RuntimeError(detail)
                wrapped.name, wrapped.message, wrapped.cause = 'Error', detail, error
                wrapped.__cause__ = error
                result.set_exception(wrapped)
        else:
            if not result.done():
                result.set_result(value)

    def cancel(_reason=None):
        if not result.done():
            result.set_exception(search_aborted(signal))

    task.add_done_callback(settle)
    dispose = subscribe_abort(signal, cancel)
    try:
        return await result
    finally:
        dispose()


def citation_snippets(blocks):
    snippets = {}
    for block in blocks:
        if block.get('type') != 'text':
            continue
        citations = block.get('citations')
        for citation in [] if citations is None else citations:
            url, text = citation.get('url'), citation.get('cited_text')
            if url is not None and len(url) > 0 and text is not None and len(text) > 0 and url not in snippets:
                snippets[url] = text
    return snippets


def map_anthropic_response(response):
    blocks = response.get('content')
    if blocks is None:
        blocks = []
    if not isinstance(blocks, list):
        raise TypeError('response.content must be an array')
    results = [block for block in blocks if block.get('type') == 'web_search_tool_result']
    if not results:
        raise WebError('DeepSeek returned no web_search_tool_result blocks; the request may not have triggered native web search',
                       'WEB_PROVIDER_ERROR')
    snippets, seen, sources = citation_snippets(blocks), set(), []
    for block in results:
        content = block.get('content')
        for item in [] if content is None else content:
            if item.get('type') != 'web_search_result':
                continue
            url = item['url']
            if len(url) == 0 or url in seen:
                continue
            seen.add(url)
            source = {'url': url}
            for key, value in (('title', item.get('title')), ('snippet', snippets.get(url)),
                               ('publishedAt', item.get('page_age'))):
                if value is not None and len(value) > 0:
                    source[key] = value
            sources.append(source)
    return {'sources': sources, 'truncated': False}


def parse_response(raw):
    def invalid_constant(value):
        raise ValueError('Invalid JSON constant: ' + value)
    # Response.json() uses replacement UTF-8 decoding and consumes a leading BOM.
    return json.loads(raw.decode('utf-8-sig', 'replace'), parse_constant=invalid_constant)


class DeepSeekSearchProvider(WebSearchProvider):
    id = DEEPSEEK_PROVIDER_ID

    def __init__(self, resolve_options):
        self.resolve_options = resolve_options

    def available(self):
        options = self.resolve_options()
        try:
            url = urllib.parse.urlsplit(options['baseURL'])
            url.port
            valid_url = bool(url.scheme) and (bool(url.netloc) if url.scheme in ('http', 'https') else True)
        except (TypeError, ValueError):
            valid_url = False
        positive = lambda value: type(value) in (int, float) and value > 0 and value % 1 == 0
        return bool(options.get('apiKey') or options.get('resolveApiKey')) and valid_url and \
            positive(options['maxTokens']) and positive(options['maxUses'])

    async def api_key(self, options, signal):
        throw_if_search_aborted(signal)
        if options.get('apiKey'):
            return options['apiKey']
        try:
            resolver = options.get('resolveApiKey')
            resolved = await abortable(resolver() if resolver else None, signal)
        except Exception as error:
            if aborted(signal) or getattr(error, 'name', None) == 'AbortError':
                raise search_aborted(signal, error) from error
            raise WebError('DeepSeek search credential resolution failed: ' + error_text(error),
                           'WEB_PROVIDER_ERROR', cause=error) from error
        if resolved is not None and len(resolved) > 0:
            return resolved
        ref = options.get('apiKeyEnv', 'DEEPSEEK_API_KEY')
        raise WebError('DeepSeek search has no API key for "' + ref + '"; store it through the credentials service'
                       ' (the web Models page writes it), export it in the launching environment, or set a literal'
                       ' "apiKey" in the web-search-deepseek config', 'WEB_PROVIDER_CREDENTIAL_MISSING')

    async def search(self, request, signal=None):
        options = self.resolve_options()
        key = await self.api_key(options, signal)
        throw_if_search_aborted(signal)
        endpoint = options['baseURL'] + '/messages'
        body = {'model': options['model'], 'max_tokens': options['maxTokens'],
                'messages': [{'role': 'user', 'content': [{'type': 'text',
                    'text': 'Perform a web search for the query: ' + request['query']}]}],
                'tools': [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': options['maxUses']}]}
        recorder = options.get('recordRequest')
        if recorder:
            recorder({'endpoint': endpoint, 'apiVersion': options['apiVersion'], 'body': body})
        throw_if_search_aborted(signal)
        linked = AbortController()
        dispose = subscribe_abort(signal, lambda _reason=None: linked.abort(getattr(signal, 'reason', None)))

        def receive():
            wire = urllib.request.Request(endpoint, data=stringify_json(body).encode('utf-8'), method='POST', headers={
                'x-api-key': key, 'authorization': 'Bearer ' + key, 'anthropic-version': options['apiVersion'],
                'content-type': 'application/json', 'accept': 'application/json', 'user-agent': 'deepseek-harness/0.0.1'})
            with open_stream(wire, linked.signal, redirect_policy='error', raise_http_errors=False) as (response, chunks):
                try:
                    return response.status, b''.join(chunks), None
                except Exception as error:
                    if aborted(linked.signal):
                        raise
                    return response.status, b'', error

        worker = asyncio.get_running_loop().run_in_executor(None, receive)
        try:
            try:
                status, raw, body_error = await asyncio.shield(worker)
            except asyncio.CancelledError as error:
                linked.abort(error)
                try:
                    await asyncio.shield(worker)
                except Exception:
                    pass
                raise
            except Exception as error:
                if aborted(signal) or getattr(error, 'name', None) == 'AbortError':
                    raise search_aborted(signal, error) from error
                raise WebError('DeepSeek search request failed: ' + str(error),
                               'WEB_PROVIDER_ERROR', cause=error) from error
        finally:
            dispose()
        throw_if_search_aborted(signal)
        if not 200 <= status < 300:
            message = 'DeepSeek API error (HTTP %s)' % status
            try:
                parsed = parse_response(raw)
                detail = parsed.get('error')
                if not isinstance(detail, str):
                    detail = detail.get('message') if isinstance(detail, dict) else None
                    if detail is None:
                        detail = parsed.get('message')
                if detail is not None and len(detail) > 0:
                    message = detail
            except Exception:
                pass
            raise WebError(message, 'WEB_PROVIDER_ERROR')
        try:
            if body_error is not None:
                raise body_error
            return map_anthropic_response(parse_response(raw))
        except WebError:
            raise
        except Exception as error:
            raise WebError('DeepSeek returned an unprocessable response body: ' + str(error),
                           'WEB_PROVIDER_ERROR', cause=error) from error


citationSnippets = citation_snippets
mapAnthropicResponse = map_anthropic_response
