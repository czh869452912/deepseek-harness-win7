import asyncio
import inspect
import json
import math
import re

from dsh.core.abort import abort_reason_error
from dsh.cordis.utils import js_to_string
from dsh.mcp.schemas import parse


PROTOCOL_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05', '2024-10-07')
ABSENT = object()


class McpError(RuntimeError):
    def __init__(self, code, message, data=ABSENT):
        self.code, self.data = code, None if data is ABSENT else data
        self.name = 'McpError'
        self.message = 'MCP error %s: %s' % (js_to_string(code), message)
        self.has_data = data is not ABSENT
        super().__init__(self.message)


class McpClientProtocol:
    def __init__(self):
        self.server_capabilities = None
        self.server_info = None
        self.protocol_version = None
        self.on_notification = None
        self.on_close = None
        self.on_error = None
        self._pending = {}
        self._next_id = 0
        self._closing = None
        self._closed = False
        self._callbacks = set()

    def _connected(self):
        raise NotImplementedError()

    async def _write(self, packet):
        raise NotImplementedError()

    async def _initialize(self):
        result = await self.request({'method': 'initialize', 'params': {
            'protocolVersion': PROTOCOL_VERSIONS[0], 'capabilities': {},
            'clientInfo': {'name': 'dsh-mcp-client', 'version': '0.0.1'}}})
        result = parse('InitializeResultSchema', result)
        version = result.get('protocolVersion')
        if version not in PROTOCOL_VERSIONS:
            raise ValueError("Server's protocol version is not supported: " + str(version))
        self.protocol_version = version
        self.server_capabilities, self.server_info = result['capabilities'], result['serverInfo']
        await self.notify('notifications/initialized')
        return self

    def _callback(self, callback, *arguments):
        if callback is None:
            return
        try:
            result = callback(*arguments)
        except Exception as error:
            if callback is not self.on_error:
                self._callback(self.on_error, error)
            return
        if not inspect.isawaitable(result):
            return
        task = asyncio.ensure_future(result)
        self._callbacks.add(task)
        def settled(completed):
            self._callbacks.discard(completed)
            if not completed.cancelled():
                completed.exception()
        task.add_done_callback(settled)

    def _disconnect(self):
        if self._closed:
            return
        self._closed = True
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpError(-32000, 'Connection closed'))
        self._pending.clear()
        self._callback(self.on_close)

    async def notify(self, method, params=None):
        packet = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            packet['params'] = params
        await self._write(packet)

    async def _cancel_request(self, params):
        await self.notify('notifications/cancelled', params)

    @staticmethod
    def _identity(value):
        if isinstance(value, str):
            return ('string', value)
        if type(value) in (int, float) and math.isfinite(value):
            return ('number', value)
        raise ValueError('Invalid MCP request id')

    @staticmethod
    def _response_identity(value):
        if isinstance(value, str):
            value = value.strip(' \t\n\r\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')
            if not value:
                value = 0
            elif re.fullmatch(r'0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+', value):
                value = float(int(value, 0))
            elif re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value):
                value = float(value)
            else:
                return None
        return ('number', value) if type(value) in (int, float) and math.isfinite(value) else None

    async def _receive(self, packet):
        packet = parse('JSONRPCMessageSchema', packet)
        if not isinstance(packet, dict) or packet.get('jsonrpc') != '2.0':
            raise ValueError('Invalid MCP envelope')
        if 'method' in packet:
            if not isinstance(packet['method'], str):
                raise ValueError('Invalid MCP method')
            if 'id' in packet:
                self._identity(packet['id'])
                response = {'jsonrpc': '2.0', 'id': packet['id']}
                if packet['method'] == 'ping':
                    response['result'] = {}
                else:
                    response['error'] = {'code': -32601, 'message': 'Method not found'}
                await self._write(response)
            else:
                notification = {'method': packet['method']}
                if 'params' in packet:
                    notification['params'] = packet['params']
                if packet['method'] == 'notifications/tools/list_changed':
                    notification = parse('ToolListChangedNotificationSchema', notification)
                self._callback(self.on_notification, notification)
            return
        identity = self._response_identity(packet.get('id'))
        if ('result' in packet) == ('error' in packet):
            raise ValueError('Invalid MCP response')
        if 'result' in packet and (not isinstance(packet['result'], dict)
                                   or set(packet) != {'jsonrpc', 'id', 'result'}):
            raise ValueError('Invalid MCP result envelope')
        error = packet.get('error')
        if 'error' in packet and (not isinstance(error, dict) or type(error.get('code')) not in (int, float)
                                 or not math.isfinite(error['code']) or int(error['code']) != error['code']
                                 or abs(error['code']) > 9007199254740991
                                 or not isinstance(error.get('message'), str)):
            raise ValueError('Invalid MCP error')
        future = self._pending.pop(identity, None)
        if future is None or future.done():
            self._callback(self.on_error, RuntimeError('Received a response for an unknown message ID: ' +
                json.dumps(packet, ensure_ascii=False, separators=(',', ':'))))
            return
        if 'error' in packet:
            future.set_exception(McpError(error['code'], error['message'], error.get('data', ABSENT)))
        else:
            future.set_result(packet['result'])

    @staticmethod
    def _aborted(signal):
        return signal is not None and (getattr(signal, 'aborted', False) or
               hasattr(signal, 'is_set') and signal.is_set())

    async def request(self, packet, signal=None, timeout=60000):
        if not self._connected():
            raise RuntimeError('Not connected')
        if self._aborted(signal):
            if hasattr(signal, 'reason'):
                raise abort_reason_error(signal)
            raise asyncio.CancelledError()
        identity = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        key = self._identity(identity)
        self._pending[key] = future
        cancelled = asyncio.Event()
        watcher = None
        detach = None
        if isinstance(signal, asyncio.Event):
            async def observe():
                await signal.wait()
                cancelled.set()
            watcher = asyncio.create_task(observe())
        elif signal is not None:
            detach = signal.add_listener('abort', lambda reason: cancelled.set())
        waiting = asyncio.create_task(cancelled.wait())
        try:
            await self._write(dict(packet, jsonrpc='2.0', id=identity))
            done, pending = await asyncio.wait((future, waiting), timeout=timeout / 1000, return_when=asyncio.FIRST_COMPLETED)
            if waiting in done or self._aborted(signal):
                if hasattr(signal, 'reason'):
                    reason = signal.reason
                    message = ('%s: %s' % (getattr(reason, 'name', 'Error'), reason)
                               if isinstance(reason, BaseException) else js_to_string(reason))
                    await self._cancel_request({'requestId': identity, 'reason': message})
                    raise McpError(-32001, message)
                raise asyncio.CancelledError()
            if future in done:
                result = future.result()
                if packet['method'] == 'tools/list':
                    result = parse('ListToolsResultSchema', result)
                return result
            await self._cancel_request({'requestId': identity, 'reason': 'McpError: MCP error -32001: Request timed out'})
            raise McpError(-32001, 'Request timed out', {'timeout': timeout})
        except asyncio.CancelledError as error:
            if not self._closed:
                await self._cancel_request({'requestId': identity, 'reason': str(error)})
            raise
        finally:
            self._pending.pop(key, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()
            if detach is not None:
                detach()
            waiting.cancel()
            if watcher is not None:
                watcher.cancel()
            await asyncio.gather(*[task for task in (waiting, watcher) if task is not None], return_exceptions=True)

    async def list_tools(self, cursor=None):
        params = {'cursor': cursor} if cursor is not None else None
        result = await self.request({'method': 'tools/list', **({'params': params} if params is not None else {})})
        if not isinstance(result, dict) or not isinstance(result.get('tools'), list):
            raise ValueError('Invalid MCP tools/list result')
        return result

    async def call_tool(self, name, args):
        result = await self.request({'method': 'tools/call', 'params': {'name': name, 'arguments': args}})
        if not isinstance(result, dict) or not isinstance(result.get('content'), list):
            raise ValueError('Invalid MCP tools/call result')
        return result

    async def close(self):
        if self._closing is None:
            self._closing = asyncio.create_task(self._close())
        await asyncio.shield(self._closing)

    async def _finish_callbacks(self):
        for task in list(self._callbacks):
            if not task.done():
                task.cancel()
        await asyncio.gather(*list(self._callbacks), return_exceptions=True)
