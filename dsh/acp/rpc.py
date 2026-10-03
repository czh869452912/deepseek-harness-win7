import asyncio
import inspect
import json
import math

from dsh.core.abort import AbortController
from dsh.cordis.json_text import stringify_json


ABSENT = object()
JSON_WHITESPACE = ' \t\n\r\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


class RequestError(RuntimeError):
    def __init__(self, code, message, data=ABSENT):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data

    def result(self):
        error = {'code': self.code, 'message': self.message}
        if self.data is not ABSENT:
            error['data'] = self.data
        return {'error': error}


def id_key(identity):
    if identity is None:
        return ('null', None)
    if isinstance(identity, str):
        return ('string', identity)
    if type(identity) in (int, float):
        number = float(identity)
        if math.isfinite(number):
            return ('number', number)
    return None


def envelope(message):
    return isinstance(message, dict) and message.get('jsonrpc') == '2.0'


def request(message):
    return envelope(message) and 'id' in message and isinstance(message.get('method'), str) and id_key(message['id']) is not None


def notification(message):
    return envelope(message) and 'id' not in message and isinstance(message.get('method'), str)


def response_shaped(message):
    return isinstance(message, dict) and 'method' not in message and any(key in message for key in ('id', 'result', 'error'))


def response(message):
    if not envelope(message) or 'method' in message or 'id' not in message or id_key(message['id']) is None:
        return False
    if ('result' in message) == ('error' in message):
        return False
    if 'error' not in message:
        return True
    error = message['error']
    return isinstance(error, dict) and type(error.get('code')) in (int, float) and float(error['code']).is_integer() and isinstance(error.get('message'), str)


async def resolved(value):
    return await value if inspect.isawaitable(value) else value


class AcpRpc:
    def __init__(self, output, on_closed=None, on_warning=None):
        self.output = output
        self.on_closed = on_closed
        self.on_warning = on_warning or (lambda detail: None)
        self.handlers = {}
        self.notifications = {}
        self.incoming = {}
        self.pending = {}
        self.tasks = set()
        self.buffer = b''
        self.lines = asyncio.Queue()
        self.reader = None
        self.input_ended = False
        self.write_tail = None
        self.closed = False
        self.closed_reason = None
        self.next_request_id = 0
        self.removals = {}

    def spawn(self, operation):
        pending = asyncio.create_task(operation)
        self.tasks.add(pending)
        def finished(completed):
            self.tasks.discard(completed)
            if not completed.cancelled() and completed.exception() is not None:
                self.close(completed.exception())
        pending.add_done_callback(finished)
        return pending

    async def send(self, message):
        if self.closed:
            raise self.closed_reason
        previous = self.write_tail
        async def write():
            if previous is not None:
                await previous
            if self.closed:
                raise self.closed_reason
            try:
                await resolved(self.output(stringify_json(message) + '\n'))
            except Exception as error:
                self.close(error)
                raise
        self.write_tail = asyncio.create_task(write())
        self.write_tail.add_done_callback(lambda completed: completed.exception() if not completed.cancelled() else None)
        await asyncio.shield(self.write_tail)

    async def notify(self, method, params=ABSENT):
        packet = {'jsonrpc': '2.0', 'method': method}
        if params is not ABSENT:
            packet['params'] = params
        await self.send(packet)

    def request(self, method, params=ABSENT, signal=None, map_response=None):
        future = asyncio.get_running_loop().create_future()
        if self.closed:
            future.set_exception(self.closed_reason)
            return future
        identity = self.next_request_id
        self.next_request_id += 1
        key = id_key(identity)
        self.pending[key] = future
        cancelled = False
        def cancel(reason=None):
            nonlocal cancelled
            if cancelled:
                return
            cancelled = True
            remove = self.removals.pop(key, None)
            if remove is not None:
                remove()
            self.spawn(self.notify('$/cancel_request', {'requestId': identity}))
        if signal is not None:
            signal.addEventListener('abort', cancel, {'once': True})
            self.removals[key] = lambda: signal.removeEventListener('abort', cancel)
        packet = {'jsonrpc': '2.0', 'id': identity, 'method': method}
        if params is not ABSENT:
            packet['params'] = params
        self.spawn(self.send(packet))
        if signal is not None and signal.aborted:
            cancel()
        async def receive():
            value = await asyncio.shield(future)
            return map_response(value) if map_response is not None else value
        task = asyncio.create_task(receive())
        task.add_done_callback(lambda completed: completed.exception() if not completed.cancelled() else None)
        return task

    def protocol_error(self, message=ABSENT, parse=False):
        error = RequestError(-32700, 'Parse error') if parse else RequestError(-32600, 'Invalid request', message)
        return {'jsonrpc': '2.0', 'id': None, **error.result()}

    def data(self, chunk):
        if self.closed or self.input_ended:
            return
        self.buffer += chunk.encode('utf-8') if isinstance(chunk, str) else chunk
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            self.lines.put_nowait(line)
        self.start_reader()

    def start_reader(self):
        if self.reader is None:
            self.reader = self.spawn(self.read_lines())

    async def read_lines(self):
        while not self.closed:
            line = await self.lines.get()
            if line is ABSENT:
                if self.write_tail is not None:
                    await self.write_tail
                self.close()
                return
            await self.line(line)
            await asyncio.sleep(0)

    async def line(self, line):
        text = line.decode('utf-8', 'replace').strip(JSON_WHITESPACE)
        if not text:
            return
        def invalid_constant(value):
            raise ValueError(value)
        try:
            message = json.loads(text, parse_int=float, parse_constant=invalid_constant)
        except ValueError:
            await self.send(self.protocol_error(parse=True))
            return
        if not isinstance(message, (dict, list)):
            await self.send(self.protocol_error(message))
            return
        self.receive(message)

    def receive(self, message):
        if self.closed:
            return
        if isinstance(message, list):
            self.batch(message)
        elif request(message) or notification(message):
            self.dispatch(message)
        elif response_shaped(message):
            self.handle_response(message)
        else:
            self.spawn(self.send(self.protocol_error(message)))

    def batch(self, batch):
        if not batch:
            self.spawn(self.send(self.protocol_error(batch)))
            return
        valid_call = any(request(message) or notification(message) for message in batch)
        valid_response = any(response(message) for message in batch)
        call_shape = any(isinstance(message, dict) and 'method' in message for message in batch)
        response_shape = any(isinstance(message, dict) and ('result' in message or 'error' in message) for message in batch)
        if not valid_call and (valid_response or response_shape and not call_shape):
            for message in batch:
                if response_shaped(message):
                    self.handle_response(message)
            return
        replies = []
        def collect(packet):
            replies.append(packet)
        operations = []
        for message in batch:
            if request(message) or notification(message):
                operations.append(self.dispatch(message, collect))
            else:
                replies.append(self.protocol_error(message))
        async def finish():
            await asyncio.gather(*operations)
            if replies:
                await self.send(replies)
        self.spawn(finish())

    def dispatch(self, message, sender=None):
        method = message['method']
        if notification(message):
            if method == '$/cancel_request':
                params = message.get('params')
                if isinstance(params, dict) and 'requestId' in params:
                    controller = self.incoming.get(id_key(params['requestId']))
                    if controller is not None:
                        controller.abort(RequestError(-32800, 'Request cancelled', {'requestId': params['requestId']}))
            async def invoke_notification():
                handler = self.notifications.get(method)
                if handler is not None:
                    try:
                        await resolved(handler(message.get('params', ABSENT)))
                    except Exception as error:
                        self.on_warning(str(error))
            return self.spawn(invoke_notification())
        controller = AbortController()
        key = id_key(message['id'])
        self.incoming[key] = controller
        handler = self.handlers.get(method)
        if handler is None:
            operation = None
        else:
            try:
                operation = handler(message.get('params', ABSENT), controller.signal)
            except Exception as error:
                async def failed(failure=error):
                    raise failure
                operation = failed()
        if handler is not None and not inspect.isawaitable(operation):
            packet = {'jsonrpc': '2.0', 'id': message['id'], 'result': operation}
            if self.incoming.get(key) is controller:
                self.incoming.pop(key, None)
            return self.spawn(resolved(sender(packet))) if sender is not None else self.spawn(self.send(packet))
        async def invoke():
            try:
                if handler is None:
                    raise RequestError(-32601, '"Method not found": ' + method, {'method': method})
                result = {'result': await operation}
            except RequestError as error:
                result = error.result()
            except Exception as error:
                if controller.signal.aborted and (getattr(error, 'name', None) == 'AbortError'
                                                   or getattr(error, 'code', None) == 'ABORT_ERR'):
                    reason = controller.signal.reason
                    if isinstance(reason, RequestError) and reason.code == -32800:
                        result = reason.result()
                    else:
                        result = RequestError(-32800, 'Request cancelled', {} if isinstance(reason, Exception) else reason).result()
                else:
                    try:
                        data = json.loads(str(error)) if str(error) else {}
                    except ValueError:
                        data = {'details': str(error)}
                    result = RequestError(-32603, 'Internal error', data).result()
            finally:
                if self.incoming.get(key) is controller:
                    self.incoming.pop(key, None)
            if not self.closed:
                packet = {'jsonrpc': '2.0', 'id': message['id'], **result}
                await resolved(sender(packet) if sender is not None else self.send(packet))
        return self.spawn(invoke())

    def handle_response(self, message):
        key = id_key(message.get('id'))
        pending = self.pending.pop(key, None)
        remove = self.removals.pop(key, None)
        if remove is not None:
            remove()
        if pending is None:
            self.on_warning('Got response to unknown request')
        elif not response(message):
            pending.set_exception(RequestError(-32600, 'Invalid request', message))
        elif 'error' in message:
            error = message['error']
            pending.set_exception(RequestError(error['code'], error['message'], error.get('data', ABSENT)))
        else:
            pending.set_result(message['result'])

    def end(self):
        if self.input_ended or self.closed:
            return
        self.input_ended = True
        if self.buffer:
            self.lines.put_nowait(self.buffer)
            self.buffer = b''
        self.lines.put_nowait(ABSENT)
        self.start_reader()

    def close(self, reason=None):
        if self.closed:
            return
        self.closed = True
        reason = reason if reason is not None else RuntimeError('ACP connection closed')
        self.closed_reason = reason
        for controller in list(self.incoming.values()):
            controller.abort(reason)
        for pending in self.pending.values():
            if not pending.done():
                pending.set_exception(reason)
        self.pending.clear()
        self.incoming.clear()
        for remove in self.removals.values():
            remove()
        self.removals.clear()
        if self.reader is not None and self.reader is not asyncio.current_task():
            self.reader.cancel()
        if self.on_closed is not None:
            self.on_closed(reason)

    async def drain(self):
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
