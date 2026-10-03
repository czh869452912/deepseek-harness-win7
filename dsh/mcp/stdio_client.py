import asyncio
import inspect
import json
import math
import sys

from dsh.core.abort import abort_reason_error
from dsh.cordis.utils import js_to_string
from dsh.subprocess.service import scrubbed_parent_env


PROTOCOL_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05', '2024-10-07')
ABSENT = object()


class McpError(RuntimeError):
    def __init__(self, code, message, data=ABSENT):
        self.code, self.data = code, None if data is ABSENT else data
        self.name = 'McpError'
        self.message = 'MCP error %s: %s' % (js_to_string(code), message)
        self.has_data = data is not ABSENT
        super().__init__(self.message)


class StdioMcpClient:
    def __init__(self, command, args=None, env=None, cwd=''):
        self.command, self.args, self.env, self.cwd = command, list(args or []), dict(env or {}), cwd
        self.proc = None
        self._spawn_task = None
        self.server_capabilities = None
        self.server_info = None
        self.protocol_version = None
        self.on_notification = None
        self.on_close = None
        self.on_error = None
        self._pending = {}
        self._next_id = 0
        self._reader = None
        self._stderr = None
        self._write_lock = asyncio.Lock()
        self._closing = None
        self._closed = False
        self._callbacks = set()
        self.stderr = bytearray()

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

    async def connect(self):
        if self._spawn_task is not None or self._closed or self._closing is not None:
            raise RuntimeError('MCP transport can only be started once')
        environment = scrubbed_parent_env()
        environment.update(self.env)
        try:
            options = {'creationflags': 0x08000000} if sys.platform == 'win32' else {}
            self._spawn_task = asyncio.create_task(asyncio.create_subprocess_exec(self.command, *self.args,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd or None, env=environment, **options))
            self.proc = await asyncio.shield(self._spawn_task)
            self._start_io()
            if self._closing is not None:
                await self.close()
                raise McpError(-32000, 'Connection closed')
            result = await self.request({'method': 'initialize', 'params': {
                'protocolVersion': PROTOCOL_VERSIONS[0], 'capabilities': {},
                'clientInfo': {'name': 'dsh-mcp-client', 'version': '0.0.1'}}})
            if (not isinstance(result, dict) or not isinstance(result.get('capabilities'), dict)
                    or not isinstance(result.get('serverInfo'), dict)
                    or not isinstance(result['serverInfo'].get('name'), str)
                    or not isinstance(result['serverInfo'].get('version'), str)):
                raise ValueError('Server sent invalid initialize result')
            version = result.get('protocolVersion')
            if version not in PROTOCOL_VERSIONS:
                raise ValueError("Server's protocol version is not supported: " + str(version))
            for name in ('tools', 'prompts', 'resources', 'logging', 'completions', 'tasks'):
                if name in result['capabilities'] and not isinstance(result['capabilities'][name], dict):
                    raise ValueError('Invalid MCP capability: ' + name)
            for name in ('tools', 'prompts', 'resources'):
                capability = result['capabilities'].get(name, {})
                for option in ('listChanged', 'subscribe'):
                    if option in capability and type(capability[option]) is not bool:
                        raise ValueError('Invalid MCP capability: %s.%s' % (name, option))
            if 'instructions' in result and not isinstance(result['instructions'], str):
                raise ValueError('Invalid MCP instructions')
            self.protocol_version = version
            self.server_capabilities, self.server_info = result['capabilities'], result['serverInfo']
            await self.notify('notifications/initialized')
            return self
        except OSError as error:
            await self.close()
            raise McpError(-32000, 'Connection closed') from error
        except BaseException:
            await self.close()
            raise

    def _start_io(self):
        if self._reader is None:
            self._reader = asyncio.create_task(self._read())
            self._stderr = asyncio.create_task(self._read_stderr())

    async def _write(self, packet):
        async with self._write_lock:
            if self.proc is None or self._closed or self.proc.stdin.is_closing():
                raise RuntimeError('Not connected')
            self.proc.stdin.write((json.dumps(packet, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8'))
            await self.proc.stdin.drain()

    async def notify(self, method, params=None):
        packet = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            packet['params'] = params
        await self._write(packet)

    @staticmethod
    def _identity(value):
        if isinstance(value, str):
            return ('string', value)
        if type(value) in (int, float) and math.isfinite(value):
            return ('number', value)
        raise ValueError('Invalid MCP request id')

    async def _read_stderr(self):
        while True:
            chunk = await self.proc.stderr.read(4096)
            if not chunk:
                return
            self.stderr.extend(chunk)

    async def _read(self):
        buffered = bytearray()
        try:
            while True:
                chunk = await self.proc.stdout.read(4096)
                if not chunk:
                    return
                buffered.extend(chunk)
                while b'\n' in buffered:
                    index = buffered.index(b'\n')
                    line = bytes(buffered[:index])
                    del buffered[:index + 1]
                    try:
                        packet = json.loads(line.decode('utf-8', errors='replace'),
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON number: ' + value)))
                        await self._receive(packet)
                    except (ValueError, TypeError, KeyError) as error:
                        self._callback(self.on_error, error)
        except (OSError, RuntimeError) as error:
            self._callback(self.on_error, error)
        finally:
            await self.proc.wait()
            self._disconnect()

    async def _receive(self, packet):
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
                self._callback(self.on_notification, notification)
            return
        identity = self._identity(packet['id'])
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
        if self.proc is None or self._closed:
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
                    await self.notify('notifications/cancelled', {'requestId': identity, 'reason': message})
                    raise McpError(-32001, message)
                raise asyncio.CancelledError()
            if future in done:
                result = future.result()
                if packet['method'] == 'tools/list':
                    self._validate_tools(result)
                return result
            await self.notify('notifications/cancelled', {'requestId': identity, 'reason': 'McpError: MCP error -32001: Request timed out'})
            raise McpError(-32001, 'Request timed out', {'timeout': timeout})
        except asyncio.CancelledError as error:
            if not self._closed:
                await self.notify('notifications/cancelled', {'requestId': identity, 'reason': str(error)})
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

    @staticmethod
    def _validate_tools(result):
        if not isinstance(result.get('tools'), list):
            raise ValueError('Invalid MCP tools/list result')
        if 'nextCursor' in result and not isinstance(result['nextCursor'], str):
            raise ValueError('Invalid MCP nextCursor')
        for tool in result['tools']:
            if not isinstance(tool, dict) or not isinstance(tool.get('name'), str):
                raise ValueError('Invalid MCP tool name')
            if 'description' in tool and not isinstance(tool['description'], str):
                raise ValueError('Invalid MCP tool description')
            for name in ('inputSchema', 'outputSchema'):
                if name == 'outputSchema' and name not in tool:
                    continue
                schema = tool.get(name)
                if not isinstance(schema, dict) or schema.get('type') != 'object':
                    raise ValueError('Invalid MCP %s' % name)
                if 'required' in schema and (not isinstance(schema['required'], list)
                        or any(not isinstance(value, str) for value in schema['required'])):
                    raise ValueError('Invalid MCP %s.required' % name)
                if 'properties' in schema and (not isinstance(schema['properties'], dict)
                        or any(not isinstance(value, dict) for value in schema['properties'].values())):
                    raise ValueError('Invalid MCP %s.properties' % name)

    async def call_tool(self, name, args):
        result = await self.request({'method': 'tools/call', 'params': {'name': name, 'arguments': args}})
        if not isinstance(result, dict) or not isinstance(result.get('content'), list):
            raise ValueError('Invalid MCP tools/call result')
        return result

    async def close(self):
        if self._closing is None:
            self._closing = asyncio.create_task(self._close())
        await asyncio.shield(self._closing)

    async def _close(self):
        if self.proc is None and self._spawn_task is not None:
            try:
                self.proc = await asyncio.shield(self._spawn_task)
                self._start_io()
            except OSError:
                pass
        if self.proc is not None:
            self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), 2)
            except asyncio.TimeoutError:
                if self.proc.returncode is None:
                    self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), 2)
                except asyncio.TimeoutError:
                    if self.proc.returncode is None:
                        self.proc.kill()
                    await asyncio.wait_for(self.proc.wait(), 1)
        self._disconnect()
        for task in (self._reader, self._stderr):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*[task for task in (self._reader, self._stderr) if task is not None], return_exceptions=True)
        for task in list(self._callbacks):
            if not task.done():
                task.cancel()
        await asyncio.gather(*list(self._callbacks), return_exceptions=True)
