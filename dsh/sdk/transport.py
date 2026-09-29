"""Line-framed JSON-RPC over caller-owned streams, with detachable listeners."""
import asyncio
import codecs
import inspect
import json
import uuid

from dsh.core.cancellation import aborted


class JsonRpcResponseError(RuntimeError):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.data = code, data


class JsonRpcLineTransport:
    def __init__(self, input_stream, output_stream):
        self.input, self.output = input_stream, output_stream
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.buffer = ''
        self.started = False
        self.request_handler = self.notification_handler = None
        self.pending, self.tasks = {}, set()

    def start(self):
        if self.started:
            return
        self.started = True
        self.input.on('data', self.on_data)
        self.input.on('error', self.on_error)
        self.input.on('end', self.on_end)

    def close(self):
        for event, callback in [('data', self.on_data), ('error', self.on_error), ('end', self.on_end)]:
            self.input.off(event, callback)
        self.fail_pending(RuntimeError('JSON-RPC transport closed'))

    def on_request(self, handler):
        self.request_handler = handler

    def on_notification(self, handler):
        self.notification_handler = handler

    def write(self, message):
        self.output.write(json.dumps(message, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
        # Python's redirected stdout is block-buffered; a frame must reach
        # the SDK client without waiting for another frame or process exit.
        self.output.flush()

    def notify(self, method, params=None):
        self.write(dict(jsonrpc='2.0', method=method, **({'params': params} if params is not None else {})))

    async def flush(self):
        result = self.output.flush()
        if inspect.isawaitable(result):
            await result

    async def request(self, method, params, signal=None):
        if aborted(signal):
            raise RuntimeError('JSON-RPC request aborted: ' + str(getattr(signal, 'reason', None)))
        identity = 'req_' + uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[identity] = future
        async def watch():
            while not future.done():
                if aborted(signal):
                    future.set_exception(RuntimeError('JSON-RPC request aborted: ' + str(getattr(signal, 'reason', None))))
                    return
                await asyncio.sleep(.01)
        monitor = asyncio.create_task(watch()) if signal is not None else None
        try:
            self.write(dict(jsonrpc='2.0', id=identity, method=method, params=params))
            return await future
        finally:
            self.pending.pop(identity, None)
            if monitor is not None:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)

    def on_data(self, chunk):
        self.buffer += chunk if isinstance(chunk, str) else self.decoder.decode(chunk)
        self.drain_lines()

    def drain_lines(self):
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line.strip():
                task = asyncio.create_task(self.handle_line(line.strip()))
                self.tasks.add(task)
                task.add_done_callback(self.retire)

    def retire(self, task):
        self.tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                self.fail_pending(error)

    def fail_pending(self, error):
        pending, self.pending = self.pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(error)

    def on_error(self, error):
        self.fail_pending(error)

    def on_end(self):
        self.buffer += self.decoder.decode(b'', final=True)
        self.drain_lines()
        self.fail_pending(RuntimeError('JSON-RPC input closed'))

    async def handle_line(self, line):
        try:
            frame = json.loads(line)
        except ValueError:
            return
        if not isinstance(frame, dict):
            return
        identity, method = frame.get('id'), frame.get('method')
        valid_id = type(identity) in (str, int, float)
        params = frame.get('params') if isinstance(frame.get('params'), dict) else {}
        if valid_id and isinstance(method, str):
            if self.request_handler is None:
                self.write(dict(jsonrpc='2.0', id=identity, error=dict(code=-32601, message='method not found: ' + method)))
                return
            try:
                result = self.request_handler(method, params)
                if inspect.isawaitable(result):
                    result = await result
                self.write(dict(jsonrpc='2.0', id=identity, result=result))
            except Exception as error:
                self.write(dict(jsonrpc='2.0', id=identity, error=dict(code=-32603, message=str(error))))
        elif valid_id:
            future = self.pending.pop(identity, None)
            if future is None or future.done():
                return
            error = frame.get('error')
            if isinstance(error, dict):
                future.set_exception(JsonRpcResponseError(error.get('code'), error.get('message', 'JSON-RPC error'), error.get('data')))
            else:
                future.set_result(frame.get('result'))
        elif isinstance(method, str) and self.notification_handler is not None:
            self.notification_handler(method, params)

    onRequest = on_request
    onNotification = on_notification
