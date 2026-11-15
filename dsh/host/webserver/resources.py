"""Fetch resource adaptation for Python's dict requests and async byte bodies."""
import asyncio
import inspect
import re
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from dsh.core.abort import AbortController


def request_target(value):
    """Resolve the HTTP placeholder target and canonical URL path segments."""
    value = re.sub('[\t\r\n]', '', value).strip(''.join(chr(i) for i in range(33))).replace('\\', '/')
    parsed = urlsplit(urljoin('http://x/', value))
    parts, original = [], (parsed.path or '/').split('/')
    for index, part in enumerate(original):
        dot = re.sub('%2e', '.', part, flags=re.IGNORECASE)
        if dot in ('.', '..'):
            if dot == '..' and parts and parts != ['']:
                parts.pop()
            if index == len(original) - 1:
                parts.append('')
        else:
            parts.append(part)
    path = quote('/'.join(parts) or '/', safe="/%:@!$&'()*+,;=-._~[]|^")
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def request_path(request):
    if 'url' in request:
        return urlsplit(request_target(request['url'])).path or '/'
    return request.get('path', '/')


async def invoke(resource, request, peer):
    answer = resource(request, peer)
    return await answer if inspect.isawaitable(answer) else answer


async def cancel_body(body):
    close = getattr(body, 'aclose', None)
    if close is not None:
        result = close()
        if inspect.isawaitable(result):
            await result


async def without_body(response):
    await cancel_body(response.get('body'))
    return dict(response, body=None)


async def write_response(writer, response, signal):
    writer.write_status(response['status'])
    for key, value in response.get('headers', {}).items():
        writer.write_header(key, str(value))
    body = response.get('body')
    if isinstance(body, str):
        body = body.encode('utf-8')
    if body is None:
        await writer.send_headers()
        await writer.finish()
    elif isinstance(body, (bytes, bytearray, memoryview)):
        if not signal.aborted:
            await writer.send_headers()
            writer.write_body(bytes(body))
            await writer.finish()
    else:
        await writer.send_headers()
        iterator = body.__aiter__()
        cancelled = asyncio.create_task(signal.wait_aborted())
        pending = None
        ended = False
        try:
            while not signal.aborted:
                pending = asyncio.ensure_future(iterator.__anext__())
                await asyncio.wait((pending, cancelled), return_when=asyncio.FIRST_COMPLETED)
                if signal.aborted:
                    return
                try:
                    chunk = await pending
                except StopAsyncIteration:
                    ended = True
                    break
                await writer.write_chunk(chunk)
            if not signal.aborted:
                await writer.finish()
        finally:
            cancelled.cancel()
            if pending is not None and not pending.done():
                pending.cancel()
            await asyncio.gather(*([cancelled, pending] if pending is not None else [cancelled]), return_exceptions=True)
            if not ended:
                await cancel_body(iterator)


def resource_handler(resource):
    async def handler(request, writer):
        method = request['method']
        if method not in ('GET', 'HEAD'):
            writer.write_status(405); writer.write_header('allow', 'GET, HEAD')
            await writer.finish()
            return
        controller = AbortController()
        async def disconnected():
            reader = request.get('reader')
            if reader is None:
                return
            while not getattr(reader, '_eof', False) and reader.exception() is None:
                await asyncio.sleep(.01)
            controller.abort()
        monitor = asyncio.create_task(disconnected())
        try:
            url = request_target(request.get('raw_url', request.get('url', request.get('path', '/'))))
            response = await invoke(resource, dict(request, url=url, signal=controller.signal), None)
            if method == 'HEAD':
                response = await without_body(response)
            if controller.signal.aborted:
                await cancel_body(response.get('body'))
                return
            await write_response(writer, response, controller.signal)
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
    handler.resource = resource
    handler.defer_body = True
    return handler
