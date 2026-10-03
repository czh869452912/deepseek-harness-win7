import asyncio
import queue
import threading

from dsh.acp.content import AcpContentError
from dsh.acp.errors import AcpInternalError, AcpInvalidParamsError
from dsh.acp.model_control import AcpModelConfigError
from dsh.acp.parameters import validate_params
from dsh.acp.rpc import AcpRpc, RequestError
from dsh.boot.cmdline import internals


class StdioWriter:
    def __init__(self, output):
        self.output = output
        self.jobs = queue.Queue()
        self.pending = set()
        self.lock = threading.Lock()
        self.closed = False
        self.thread = None

    async def write(self, content):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.add_done_callback(lambda completed: completed.exception() if not completed.cancelled() else None)
        with self.lock:
            if self.closed:
                raise RuntimeError('ACP output closed')
            self.pending.add((loop, future))
            self.jobs.put((loop, future, content))
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='dsh-acp-stdout', daemon=True)
                self.thread.start()
        await asyncio.shield(future)

    def run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            loop, future, content = job
            with self.lock:
                if self.closed:
                    continue
            error = None
            try:
                self.output.write(content)
                self.output.flush()
            except Exception as failure:
                error = failure
            def settle(loop=loop, future=future, error=error):
                with self.lock:
                    self.pending.discard((loop, future))
                if not future.done():
                    if error is None:
                        future.set_result(None)
                    else:
                        future.set_exception(error)
            try:
                loop.call_soon_threadsafe(settle)
            except RuntimeError:
                return

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            pending = list(self.pending)
            self.pending.clear()
            self.jobs.put(None)
        for loop, future in pending:
            if not future.done():
                future.set_exception(RuntimeError('ACP output closed'))


def mount_acp_stdio(ctx, bridge):
    stream = bridge.config.get('stream')
    if stream is None:
        stdin = ctx.get('acpStdin')
        if stdin is None:
            return None
        output = internals.stdout
    elif isinstance(stream, dict):
        stdin, output = stream['input'], stream['output']
    else:
        stdin, output = stream.input, stream.output
    writer = None if callable(output) else StdioWriter(output)
    closing = [None]
    detached = [False]

    def warning(detail):
        ctx.logger.warn('acp: ' + detail)

    def detach():
        if detached[0]:
            return
        detached[0] = True
        for event, callback in [('data', connection.data), ('end', connection.end), ('error', connection.close)]:
            stdin.off(event, callback)

    def closed(reason):
        detach()
        if writer is not None:
            writer.close()
        closing[0] = asyncio.create_task(bridge.close(ctx))
        def settled(task):
            if not task.cancelled() and task.exception() is not None:
                warning('ACP bridge teardown failed: ' + str(task.exception()))
        closing[0].add_done_callback(settled)

    connection = AcpRpc(output if writer is None else writer.write, closed, warning)
    methods = {
        'initialize': bridge.initialize, 'authenticate': bridge.authenticate,
        'session/new': bridge.new_session, 'session/list': bridge.list_sessions,
        'session/resume': bridge.resume_session, 'session/close': bridge.close_session,
        'session/set_config_option': bridge.set_config_option, 'session/prompt': bridge.prompt,
    }
    cancellable = {'session/new', 'session/list', 'session/resume', 'session/set_config_option', 'session/prompt'}

    def handler(method, operation):
        async def invoke(params, signal):
            parsed = validate_params(method, params)
            try:
                result = await operation(ctx, parsed, signal) if method in cancellable else await operation(ctx, parsed)
                return {} if method == 'authenticate' else result
            except AcpInvalidParamsError as error:
                raise RequestError(-32602, 'Invalid params: ' + str(error)) from error
            except AcpInternalError as error:
                raise RequestError(-32603, 'Internal error: ' + str(error)) from error
            except AcpContentError as error:
                code, message = (-32602, 'Invalid params') if error.kind == 'invalid' else (-32603, 'Internal error')
                raise RequestError(code, message + ': ' + error.message) from error
            except AcpModelConfigError as error:
                if method != 'session/set_config_option':
                    raise
                raise RequestError(-32602, 'Invalid params: ' + str(error)) from error
        return invoke

    for method, operation in methods.items():
        connection.handlers[method] = handler(method, operation)

    async def cancel(params):
        await bridge.cancel(ctx, validate_params('session/cancel', params))
    connection.notifications['session/cancel'] = cancel

    async def dispose():
        detach()
        try:
            if connection.input_ended and not connection.closed and connection.reader is not None:
                await asyncio.shield(connection.reader)
        finally:
            connection.close()
        if closing[0] is not None:
            await asyncio.shield(closing[0])
        cache = ctx.get('sessionProjectionCache')
        if cache is not None:
            await cache.drain()
    ctx.on('app/stopping', dispose)
    ctx.effect(lambda: dispose, label='acp.stdio')
    stdin.on('data', connection.data)
    stdin.on('end', connection.end)
    stdin.on('error', connection.close)
    if getattr(stdin, 'readableEnded', False):
        connection.end()
    return connection
