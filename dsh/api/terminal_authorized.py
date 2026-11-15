"""One provider-owned terminal, original xterm screen, and detachable Remote views."""
import asyncio
import codecs
import inspect

from dsh.api.terminal_retention_authorized import CleanupPromise, TerminalRetention
from dsh.api.terminal_stream_authorized import TerminalFollower
from dsh.core.session.current import safe
from dsh.terminal.grapheme import utf8
from dsh.typert.remote import RemoteError, remote_error_of


class AgentTerminalError(Exception):
    name = 'AgentTerminalError'

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def consume(task):
    if not task.cancelled():task.exception()


class BrowserTerminal:
    """The controller supplies an allocated canonical handle and an owned screen.

    Screen allocation is asynchronous on the Win7 worker. Its controller must
    acquire it before constructing this owner, and roll back the PTY on failure.
    Provider output is an async byte iterator, independent of browser lifetimes.
    """
    def __init__(self, handle, info, screen, max_buffered_bytes, release=None):
        self.handle, self.info, self.screen = handle, info, screen
        self.max_buffered_bytes, self.release = max_buffered_bytes, release
        self.followers = set();self.sequence = 0;self.operations = None
        self.exited = False;self.closing = None;self.screenDisposed = False
        self.retention = None;self.controller = None;self.changes = 0
        self.waiters = set();self.state_listener = None
        self.drained = asyncio.ensure_future(self._consume());self.drained.add_done_callback(consume)

    def monitor(self, policy, closing, closed, failed):
        async def terminate():
            closing();await self.closeProcess();closed()
        self.retention = TerminalRetention(policy, self.handle.inspectActivity, terminate, failed)

    def retain(self, signal):
        if self.retention is None:raise RuntimeError('Terminal has not been committed')
        return self.retention.retain(signal)

    def enqueue(self, operation):
        previous = self.operations
        async def apply():
            if previous is not None:
                try:await asyncio.shield(previous)
                except Exception:pass
            result = operation()
            return await result if inspect.isawaitable(result) else result
        pending = asyncio.ensure_future(apply());pending.add_done_callback(consume)
        self.operations = pending
        return pending

    async def attach(self, input, limits, signal, inputWindow=None):
        signal.throwIfAborted();follower = TerminalFollower(self.max_buffered_bytes)
        async def baseline():
            signal.throwIfAborted();self.controller = follower;self.broadcastState()
            snapshot = dict(type='snapshot',sequence=self.sequence,screen=await self.screen.snapshot(),
                info=self.info,writable=self.writable(follower))
            if inputWindow is not None:snapshot['inputWindow'] = inputWindow
            self.followers.add(follower)
            return snapshot
        pending = self.enqueue(baseline);uplink = commands = None
        try:
            value = await asyncio.shield(pending)
            uplink = input.__aiter__()
            async def pump():
                try:await self.consumeInput(uplink,follower,limits,signal)
                except Exception as error:follower.fail(error)
            commands = asyncio.ensure_future(pump());commands.add_done_callback(consume)
            yield value
            async for frame in follower.read(signal):yield frame
        finally:
            # Python task cancellation can interrupt the first async-generator
            # read while the non-cancellable baseline is queued in the owner.
            try:await asyncio.shield(pending)
            except Exception:pass
            self.followers.discard(follower);follower.close()
            if self.controller is follower:self.controller = None;self.broadcastState()
            if uplink is not None:
                close = getattr(uplink,'aclose',None)
                if close is not None:await close()
            if commands is not None:await asyncio.shield(commands)

    async def consumeInput(self, input, follower, limits, signal):
        sequence = 0
        while True:
            try:command = await input.__anext__()
            except StopAsyncIteration:return
            if signal.aborted or not follower.active:return
            sequence += 1
            if not safe(command['sequence']) or command['sequence'] != sequence:
                raise RuntimeError('Terminal input sequence has a gap')
            async def apply():
                signal.throwIfAborted();self.requireController(follower)
                if command['type'] == 'write':
                    if len(utf8(command['data'])) > limits['maxInputBytes']:
                        raise RuntimeError('Terminal input exceeds the configured limit')
                    if command.get('typed') is True and self.info['control'] == 'agent':
                        self.info = dict(self.info,control='user');self.broadcastState()
                    if self.retention is not None:self.retention.invalidate()
                    await self.handle.write(command['data'])
                elif command['type'] == 'resize':
                    cols,rows = command['cols'],command['rows']
                    if not safe(cols) or not 2 <= cols <= limits['maxCols'] or not safe(rows) or not 1 <= rows <= limits['maxRows']:
                        raise RuntimeError('Terminal dimensions exceed the configured limits')
                    await self.handle.resize(cols,rows);await self.screen.resize(cols,rows)
                    self.info = dict(self.info,cols=cols,rows=rows);self.broadcastState()
                else:raise RuntimeError('Unexpected terminal input type')
            try:await asyncio.shield(self.enqueue(apply));follower.push(dict(type='ack',sequence=sequence))
            except Exception as error:
                failure = remote_error_of(error)
                if failure is not None and failure['code'] == 'terminal/control-unavailable':
                    follower.push(dict(type='ack',sequence=sequence,refusal=failure['details']['reason']))
                elif self.exited:follower.push(dict(type='ack',sequence=sequence,refusal='not-running'))
                else:raise

    def writable(self, follower):
        return not self.exited and self.closing is None and self.info['state'] == 'running' and self.controller is follower

    def broadcastState(self):
        for follower in self.followers:follower.push(dict(type='state',info=self.info,writable=self.writable(follower)))
        self.advance()
        if self.state_listener is not None:self.state_listener()

    def setStateListener(self, listener):self.state_listener = listener

    async def inspectActivity(self):return (await self.handle.inspectActivity())['state']

    @property
    def pid(self):return self.handle.pid

    @property
    def revision(self):return self.changes

    async def changed(self, after, signal):
        while self.changes <= after:
            signal.throwIfAborted();waiting = asyncio.get_running_loop().create_future()
            def wake(*_):
                signal.removeEventListener('abort',wake);self.waiters.discard(wake)
                if not waiting.done():waiting.set_result(None)
            self.waiters.add(wake);signal.addEventListener('abort',wake,dict(once=True))
            try:await waiting
            finally:signal.removeEventListener('abort',wake);self.waiters.discard(wake)
        return self.changes

    def advance(self):
        self.changes += 1;waiters = list(self.waiters);self.waiters.clear()
        for wake in waiters:wake()

    async def agentWrite(self, data):
        async def apply():
            self.requireAgentControl()
            if self.retention is not None:self.retention.invalidate()
            await self.handle.write(data)
        await asyncio.shield(self.enqueue(apply))

    async def agentSignal(self, signal):
        async def apply():
            self.requireAgentControl()
            if self.retention is not None:self.retention.invalidate()
            return await self.handle.signalForeground(signal)
        return await asyncio.shield(self.enqueue(apply))

    async def inspectForeground(self):return await self.handle.inspectForeground()

    async def drain(self):await asyncio.shield(self.enqueue(lambda:None))

    def readScreen(self, request):self.requireScreen();return self.screen.read(request)
    def markScreen(self):self.requireScreen();return TerminalMark(self,self.screen.mark())

    def requireAgentControl(self):
        if self.exited or self.closing is not None or self.info['state'] != 'running':
            raise AgentTerminalError('not-running','The terminal is not running')
        if self.info['control'] != 'agent':raise AgentTerminalError('user-control','The user has taken over this terminal')

    @property
    def screenReleased(self):return self.screenDisposed

    def requireScreen(self):
        if self.screenDisposed:raise AgentTerminalError('unavailable','The terminal was closed')

    def rename(self, title):self.info = dict(self.info,title=title);self.broadcastState()

    def close(self):return self.retention.close() if self.retention is not None else self.closeProcess()

    def dispose(self):return self.retention.dispose() if self.retention is not None else self.closeProcess()

    def closeProcess(self):
        if self.closing is None:
            async def close():
                try:
                    await self.handle.terminate();await asyncio.shield(self.drained)
                    if self.release is not None:await self.release()
                    for follower in self.followers:follower.finish()
                    self.followers.clear();self.screenDisposed = True;await self.screen.dispose()
                except Exception:self.closing = None;raise
            self.closing = CleanupPromise(close())
        return self.closing

    def requireController(self, follower):
        if self.exited or self.closing is not None or self.info['state'] != 'running':
            raise RemoteError('terminal/control-unavailable','Terminal is not running',dict(reason='not-running'))
        if self.controller is not follower or not follower.active:
            raise RemoteError('terminal/control-unavailable','Terminal input is controlled by another attachment',dict(reason='read-only'))

    async def _consume(self):
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        async def outcome():
            try:
                value = await asyncio.shield(self.handle.done);self.exited = True
                return value,None
            except Exception as error:return None,error
        finished = asyncio.ensure_future(outcome());finished.add_done_callback(consume)
        try:
            async for chunk in self.handle.output:await self.output(decoder.decode(chunk,final=False))
            await self.output(decoder.decode(b'',final=True));result,error = await asyncio.shield(finished)
            if error is not None:raise error
            self.info = dict(self.info,state='exited',exitCode=result['exitCode'])
        except Exception as error:self.info = dict(self.info,state='failed',error=str(error))
        self.broadcastState()

    async def output(self, data):
        if not data:return
        async def apply():
            await self.screen.write(data);self.sequence += 1
            frame = dict(type='output',sequence=self.sequence,data=data)
            for follower in self.followers:follower.push(frame)
            self.advance()
        await asyncio.shield(self.enqueue(apply))


class TerminalMark:
    def __init__(self, terminal, mark):self.terminal,self.mark = terminal,mark
    def lines(self):self.terminal.requireScreen();return self.mark.lines()
    def dispose(self):self.mark.dispose()


class AgentTerminalHandle:
    def __init__(self, terminal, close):self.terminal,self.close_terminal = terminal,close
    @property
    def id(self):return self.terminal.info['id']
    @property
    def pid(self):return self.terminal.pid
    @property
    def info(self):return self.terminal.info
    @property
    def revision(self):return self.terminal.revision
    async def changed(self, after, signal):return await self.terminal.changed(after,signal)
    async def write(self, data):await self.terminal.agentWrite(data)
    async def drain(self):await self.terminal.drain()
    def read(self, request):return self.terminal.readScreen(request)
    def mark(self):return self.terminal.markScreen()
    async def inspectForeground(self):return await self.terminal.inspectForeground()
    async def signal(self, signal):return await self.terminal.agentSignal(signal)
    async def close(self):
        if self.info['control'] != 'agent':raise AgentTerminalError('user-control','The user has taken over this terminal')
        await self.close_terminal()
