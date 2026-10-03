import asyncio
import codecs
import json
import re
import ssl
from urllib.parse import urlsplit

from dsh.mcp.protocol import McpClientProtocol


class StreamableHTTPError(RuntimeError):
    def __init__(self, code, message):
        self.name = 'Error'
        self.code = code
        self.message = 'Streamable HTTP error: ' + message
        super().__init__(self.message)


class InvalidMcpUrlError(TypeError):
    def __init__(self, value):
        self.name = 'TypeError'
        self.code = 'ERR_INVALID_URL'
        self.input = value
        super().__init__('Invalid URL')


class HttpResponse:
    def __init__(self, reader, writer, status, reason, headers):
        self.reader, self.writer = reader, writer
        self.status, self.reason, self.headers = status, reason, headers

    async def chunks(self):
        if self.status in (204, 304) or self.status < 200:
            return
        if 'chunked' in self.headers.get('transfer-encoding', '').lower():
            while True:
                size = int((await self.reader.readline()).split(b';', 1)[0].strip(), 16)
                if not size:
                    while (await self.reader.readline()) not in (b'\r\n', b'\n', b''):
                        pass
                    return
                remaining = size
                while remaining:
                    chunk = await self.reader.readexactly(min(remaining, 65536))
                    remaining -= len(chunk)
                    yield chunk
                if await self.reader.readexactly(2) != b'\r\n':
                    raise ValueError('Invalid HTTP chunk boundary')
        elif 'content-length' in self.headers:
            remaining = int(self.headers['content-length'])
            while remaining:
                chunk = await self.reader.readexactly(min(remaining, 65536))
                remaining -= len(chunk)
                yield chunk
        else:
            while True:
                chunk = await self.reader.read(65536)
                if not chunk:
                    return
                yield chunk

    async def read(self):
        chunks = [chunk async for chunk in self.chunks()]
        return b''.join(chunks)


class StreamableHttpMcpClient(McpClientProtocol):
    def __init__(self, url, headers=None):
        super().__init__()
        self.url = url
        self.headers = {name.lower(): str(value) for name, value in (headers or {}).items()}
        try:
            self._url = urlsplit(url)
            if not self._url.scheme or not self._url.hostname:
                raise ValueError()
            self._port = self._url.port
        except (ValueError, TypeError):
            raise InvalidMcpUrlError(url)
        self.session_id = None
        self._started = False
        self._tasks = set()
        self._writers = set()
        self._server_retry_ms = None

    def _connected(self):
        return self._started and not self._closed

    async def connect(self):
        if self._started or self._closed or self._closing is not None:
            raise RuntimeError('MCP transport can only be started once')
        self._started = True
        try:
            return await self._initialize()
        except BaseException:
            await self.close()
            raise

    def _owned(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        def settled(completed):
            self._tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()
        task.add_done_callback(settled)
        return task

    def _common_headers(self):
        headers = {}
        if self.session_id:
            headers['mcp-session-id'] = self.session_id
        if self.protocol_version:
            headers['mcp-protocol-version'] = self.protocol_version
        headers.update(self.headers)
        return headers

    async def _request_http(self, method, headers, body=b''):
        if not self._connected():
            raise RuntimeError('Not connected')
        if self._url.scheme not in ('http', 'https'):
            raise TypeError('fetch failed')
        secure = self._url.scheme == 'https'
        host = self._url.hostname
        port = self._port or (443 if secure else 80)
        context = ssl.create_default_context() if secure else None
        reader, writer = await asyncio.open_connection(host, port, ssl=context,
            server_hostname=host if secure else None)
        self._writers.add(writer)
        if self._closed:
            await self._release_writer(writer)
            raise RuntimeError('Not connected')
        try:
            authority = '[' + host + ']' if ':' in host else host
            if port != (443 if secure else 80):
                authority += ':' + str(port)
            packet_headers = {'host': authority, 'connection': 'close', 'accept': '*/*'}
            packet_headers.update(headers)
            if method == 'POST':
                packet_headers['content-length'] = str(len(body))
            path = self._url.path or '/'
            if self._url.query:
                path += '?' + self._url.query
            lines = ['%s %s HTTP/1.1' % (method, path)]
            for name, value in packet_headers.items():
                if '\r' in name + value or '\n' in name + value:
                    raise ValueError('Invalid MCP HTTP header')
                lines.append(name + ': ' + value)
            writer.write(('\r\n'.join(lines) + '\r\n\r\n').encode('latin-1') + body)
            await writer.drain()
            while True:
                status_line = (await reader.readline()).decode('latin-1').rstrip('\r\n')
                version, status, reason = status_line.split(' ', 2)
                response_headers = {}
                while True:
                    line = await reader.readline()
                    if line in (b'\r\n', b'\n'):
                        break
                    if not line:
                        raise ValueError('Incomplete MCP HTTP headers')
                    name, value = line.decode('latin-1').split(':', 1)
                    response_headers[name.lower()] = value.strip()
                if int(status) >= 200:
                    return HttpResponse(reader, writer, int(status), reason, response_headers)
        except BaseException:
            await self._release_writer(writer)
            raise

    async def _release_writer(self, writer):
        self._writers.discard(writer)
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 1)
        except asyncio.TimeoutError:
            writer.transport.abort()
        except (OSError, RuntimeError):
            pass

    async def _write(self, packet):
        if not self._connected():
            raise RuntimeError('Not connected')
        if 'method' in packet and 'id' in packet:
            async def send_request():
                try:
                    await self._send(packet)
                except Exception as error:
                    future = self._pending.pop(self._identity(packet['id']), None)
                    if future is not None and not future.done():
                        future.set_exception(error)
            self._owned(send_request())
        else:
            await self._send(packet)

    async def _send(self, packet):
        response = None
        try:
            headers = self._common_headers()
            headers.update({'content-type': 'application/json', 'accept': 'application/json, text/event-stream'})
            body = json.dumps(packet, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('utf-8')
            response = await self._request_http('POST', headers, body)
            session_id = response.headers.get('mcp-session-id')
            if session_id:
                self.session_id = session_id
            if not 200 <= response.status < 300:
                text = (await response.read()).decode('utf-8', errors='replace')
                raise StreamableHTTPError(response.status, 'Error POSTing to endpoint: ' + text)
            if response.status == 202:
                if packet.get('method') == 'notifications/initialized':
                    self._owned(self._get_sse())
                return
            if 'method' not in packet or 'id' not in packet:
                return
            content_type = response.headers.get('content-type')
            if content_type and 'text/event-stream' in content_type:
                await self._sse(response, False)
            elif content_type and 'application/json' in content_type:
                value = json.loads((await response.read()).decode('utf-8-sig', errors='replace'))
                for message in value if isinstance(value, list) else [value]:
                    await self._receive(message)
            else:
                raise StreamableHTTPError(-1, 'Unexpected content type: ' + (content_type if content_type is not None else 'null'))
        except Exception as error:
            if not self._closed:
                self._callback(self.on_error, error)
            raise
        finally:
            if response is not None:
                await self._release_writer(response.writer)

    async def _cancel_request(self, params):
        async def send():
            try:
                await self.notify('notifications/cancelled', params)
            except Exception as error:
                if not self._closed:
                    self._callback(self.on_error, RuntimeError('Failed to send cancellation: ' + str(error)))
        self._owned(send())

    async def _get_sse(self, last_event_id=None, attempt=0):
        response = None
        try:
            headers = self._common_headers()
            headers['accept'] = 'text/event-stream'
            if last_event_id:
                headers['last-event-id'] = last_event_id
            response = await self._request_http('GET', headers)
            if not 200 <= response.status < 300:
                if response.status == 405:
                    return
                raise StreamableHTTPError(response.status, 'Failed to open SSE stream: ' + response.reason)
            await self._sse(response, True)
        except Exception as error:
            if not self._closed:
                self._callback(self.on_error, error)
                if attempt:
                    self._callback(self.on_error, RuntimeError('Failed to reconnect SSE stream: ' + str(error)))
                    self._schedule_sse(last_event_id, attempt)
        finally:
            if response is not None:
                await self._release_writer(response.writer)

    def _schedule_sse(self, last_event_id, attempt=0):
        if self._closed:
            return
        if attempt >= 2:
            self._callback(self.on_error, RuntimeError('Maximum reconnection attempts (2) exceeded.'))
            return
        delay = self._server_retry_ms if self._server_retry_ms is not None else min(1000 * 1.5 ** attempt, 30000)
        async def retry():
            await asyncio.sleep(delay / 1000)
            if not self._closed:
                await self._get_sse(last_event_id, attempt + 1)
        self._owned(retry())

    async def _sse(self, response, reconnectable):
        decoder = codecs.getincrementaldecoder('utf-8-sig')(errors='replace')
        buffer, data, event, event_id = '', [], '', None
        last_id, received_result = None, False
        async def dispatch():
            nonlocal data, event, event_id, last_id, received_result
            if event_id:
                last_id = event_id
            payload = '\n'.join(data)
            if payload and event in ('', 'message'):
                try:
                    message = json.loads(payload)
                    await self._receive(message)
                    if isinstance(message, dict) and 'result' in message and 'id' in message:
                        received_result = True
                except (ValueError, TypeError, KeyError) as error:
                    self._callback(self.on_error, error)
            data, event, event_id = [], '', None
        try:
            async for chunk in response.chunks():
                buffer += decoder.decode(chunk)
                while True:
                    boundary = re.search(r'\r\n|\r|\n', buffer)
                    if boundary is None or boundary.group() == '\r' and boundary.end() == len(buffer):
                        break
                    line, buffer = buffer[:boundary.start()], buffer[boundary.end():]
                    if not line:
                        await dispatch()
                    elif not line.startswith(':'):
                        field, separator, value = line.partition(':')
                        if value.startswith(' '):
                            value = value[1:]
                        if field == 'data':
                            data.append(value)
                        elif field == 'event':
                            event = value
                        elif field == 'id' and '\0' not in value:
                            event_id = value
                        elif field == 'retry' and value.isascii() and value.isdigit():
                            self._server_retry_ms = int(value)
        except Exception as error:
            if not self._closed:
                self._callback(self.on_error, error)
        finally:
            if not self._closed and (reconnectable or last_id) and not received_result:
                self._schedule_sse(last_id)

    async def terminate_session(self):
        if not self.session_id:
            return
        response = await self._request_http('DELETE', self._common_headers())
        try:
            if not 200 <= response.status < 300 and response.status != 405:
                raise StreamableHTTPError(response.status, 'Failed to terminate session: ' + response.reason)
            self.session_id = None
        finally:
            await self._release_writer(response.writer)

    async def _close(self):
        self._disconnect()
        tasks = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        writers = list(self._writers)
        for writer in writers:
            writer.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(self._release_writer(writer) for writer in writers), return_exceptions=True)
        await self._finish_callbacks()
