"""Pull-driven HTTP body transport for rc.3 buffered and streaming Fetch routes."""
import asyncio
import inspect
from urllib.parse import urljoin

from dsh.core.abort import AbortController
from dsh.host.connection.http_bridge import read_body, write_response, BodyTooLarge, DEFAULT_MAX_REQUEST_BODY_BYTES


class StreamingRequestBody:
    """One bounded read at a time; encoded framing never becomes upload bytes."""
    def __init__(self, request, controller):
        self.request, self.controller, self.ended = request, controller, False
        self.claimed = False

    def __aiter__(self):
        if self.claimed:
            raise RuntimeError('request body has already been consumed')
        self.claimed = True
        return self.iterate()

    async def iterate(self):
        try:
            request = self.request
            if not request.get('body_deferred'):
                if request.get('body'):
                    yield request['body']
            else:
                reader, headers = request['reader'], request['headers']
                if headers.get('transfer-encoding', '').lower() == 'chunked':
                    while True:
                        line = await reader.readline()
                        size = int(line.split(b';', 1)[0].strip(), 16)
                        if size < 0:
                            raise ValueError('negative chunk size')
                        if size == 0:
                            while True:
                                trailer = await reader.readline()
                                if trailer in (b'\r\n', b'\n', b''):
                                    self.ended = True
                                    return
                        while size:
                            chunk = await reader.read(min(size, 65536))
                            if not chunk:
                                raise asyncio.IncompleteReadError(b'', size)
                            size -= len(chunk)
                            yield chunk
                        if await reader.readexactly(2) != b'\r\n':
                            raise ValueError('invalid chunk terminator')
                else:
                    remaining = int(headers.get('content-length', '0'))
                    if remaining < 0:
                        raise ValueError('negative body length')
                    while remaining:
                        chunk = await reader.read(min(remaining, 65536))
                        if not chunk:
                            raise asyncio.IncompleteReadError(b'', remaining)
                        remaining -= len(chunk)
                        yield chunk
            self.ended = True
        except (Exception, asyncio.CancelledError) as error:
            self.controller.abort(error)
            raise


def current_bridge_handler(connection, api, limit=DEFAULT_MAX_REQUEST_BODY_BYTES):
    async def handler(request, response):
        rejection = connection.request_rejection(request)
        if rejection is not None:
            await write_response(response, dict(status=rejection, body='unauthorized' if rejection == 401 else 'forbidden'))
            return
        controller = AbortController()
        streaming = api.requestBodyMode(request) == 'streaming'
        body = StreamingRequestBody(request, controller) if streaming else None
        if not streaming:
            try:
                body = await read_body(request, limit)
                response.request_body_read = True
            except BodyTooLarge:
                await write_response(response, dict(status=413, headers={'connection': 'close'}, body=b''))
                return
            except (ValueError, asyncio.IncompleteReadError):
                await write_response(response, dict(status=400, body='invalid request body'))
                return
        async def disconnected():
            reader = request.get('reader')
            if reader is None:
                return
            if streaming:
                # StreamReader.at_eof() stays false when unread bytes remain.
                # The fixed 3.8 transport's EOF flag permits disconnect detection
                # without racing a second read against the route's body reader.
                while not getattr(reader, '_eof', False) and reader.exception() is None:
                    await asyncio.sleep(.01)
            else:
                try:
                    while await reader.read(1024):
                        pass
                except (ConnectionError, OSError):
                    pass
            controller.abort('HTTP client disconnected')
        input_closed = getattr(request.get('reader'), 'input_closed', None)
        monitor = None
        completed = False

        def client_closed(_):
            if not completed:
                controller.abort('HTTP client disconnected')

        if input_closed is None:
            monitor = asyncio.create_task(disconnected())
        elif input_closed.done():
            client_closed(input_closed)
        else:
            input_closed.add_done_callback(client_closed)
        try:
            # Node's Fetch carrier constructs this against the same internal
            # base. Preserve the raw query for route-owned upload receipts.
            url = request.get('url') or urljoin('http://dsh.internal', request.get('raw_url', request['path']))
            result = api.fetch(dict(request, url=url, body=body, signal=controller.signal))
            if inspect.isawaitable(result):
                result = await result
            if streaming and not body.ended:
                result = dict(result, headers=dict(result.get('headers', {}), connection='close'))
            elif streaming:
                response.request_body_read = True
            await write_response(response, result)
        finally:
            # Normal response completion is not a cancellation in the original.
            completed = True
            if monitor is None:
                input_closed.remove_done_callback(client_closed)
            else:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
    handler.defer_body = True
    return handler
