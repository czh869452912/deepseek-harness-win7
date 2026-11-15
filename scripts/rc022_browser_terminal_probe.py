"""Paired original BrowserTerminal and actual Win7-worker screen operations."""
import asyncio
import copy
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


class Channel:
    def __init__(self):self.queue=asyncio.Queue();self.closed=False
    def __aiter__(self):return self
    async def __anext__(self):
        value=await self.queue.get()
        if value is None:raise StopAsyncIteration
        return value
    def push(self,value):self.queue.put_nowait(value)
    async def aclose(self):
        if not self.closed:self.closed=True;self.queue.put_nowait(None)


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.javascript.runtime import JavaScriptRuntime
    from dsh.terminal.screen_runtime import TerminalScreenRuntime
    from dsh.api.terminal_authorized import BrowserTerminal,AgentTerminalHandle
    ctx=Context();rows=[]
    await ctx.plugin(JavaScriptRuntime);await ctx.plugin(TerminalScreenRuntime)
    async def until(predicate):
        async def wait():
            while not predicate():await asyncio.sleep(.001)
        await asyncio.wait_for(wait(),3)
    async def fixture():
        class Handle:
            pid=123
            def __init__(self):
                self.output=Channel();self.done=asyncio.get_running_loop().create_future()
                self.writes=[];self.sizes=[];self.signals=[];self.terminated=0;self.retry=False
            async def write(self,data):self.writes.append(data)
            async def resize(self,cols,rows):self.sizes.append([cols,rows])
            async def inspectActivity(self):return dict(state='unknown',revision=0)
            async def inspectForeground(self):return dict(pgid=123,input='unknown')
            async def signalForeground(self,signal):self.signals.append(signal);return 123
            async def terminate(self):
                self.terminated+=1
                if self.retry and self.terminated==1:raise RuntimeError('cleanup failed')
                if not self.done.done():self.output.push(b'FINAL\r\n');self.done.set_result(dict(exitCode=0,signal=None))
                await self.output.aclose()
        handle=Handle();released=[]
        async def release():released.append('release')
        screen=await ctx.terminalScreens.open(dict(cols=20,rows=4,scrollback=6))
        terminal=BrowserTerminal(handle,dict(id='terminal-test',title='shell',shell=dict(path='/bin/sh',name='sh',args=['-i']),
            cwd='/workspace',cols=20,rows=4,state='running',exitCode=None,origin='agent',control='agent'),screen,100000,release)
        return terminal,handle,released
    async def attach(terminal):
        channel=Channel();abort=AbortController();frames=[];errors=[]
        stream=terminal.attach(channel,dict(maxInputBytes=12,maxCols=200,maxRows=100),abort.signal,dict(maxBufferedBytes=4096))
        frames.append(await stream.__anext__())
        async def read():
            try:
                async for frame in stream:frames.append(frame)
            except Exception as error:errors.append(str(error))
        pump=asyncio.ensure_future(read())
        async def close():abort.abort();await asyncio.wait_for(pump,2);await stream.aclose()
        return dict(channel=channel,abort=abort,frames=frames,errors=errors,pump=pump,close=close)
    def record(name,terminal,handle,released,views=()):
        rows.append(copy.deepcopy(dict(name=name,info=terminal.info,revision=terminal.revision,writes=handle.writes,
            sizes=handle.sizes,signals=handle.signals,terminated=handle.terminated,released=released,
            views=[dict(frames=v['frames'],errors=v['errors']) for v in views])))
    async def failure(operation):
        try:await operation;return None
        except Exception as error:return dict(name=getattr(error,'name',type(error).__name__),code=getattr(error,'code',None),message=str(error))
    try:
        terminal,handle,released=await fixture();agent=AgentTerminalHandle(terminal,terminal.close);views=[]
        try:
            first=await attach(terminal);views.append(first)
            handle.output.push(b'\xef\xbb\xbfhello\r\n\xe4');await until(lambda:terminal.sequence==1)
            handle.output.push(b'\xb8\xad\r\n$ ');await until(lambda:terminal.sequence==2)
            await until(lambda:len(first['frames'])==3);record('split-bom',terminal,handle,released,views)
            await agent.write('echo agent\r');await agent.signal('interrupt')
            rows.append(dict(name='agent',id=agent.id,pid=agent.pid,activity=await terminal.inspectActivity(),foreground=await agent.inspectForeground(),page=agent.read(dict(offset=0,count=10,maxBytes=1000))))
            second=await attach(terminal);views.append(second)
            await until(lambda:len(first['frames'])==4)
            first['channel'].push(dict(type='write',sequence=1,data='old'))
            await until(lambda:any(f['type']=='ack' for f in first['frames']))
            second['channel'].push(dict(type='resize',sequence=1,cols=12,rows=5))
            await until(lambda:any(f['type']=='ack' for f in second['frames']))
            second['channel'].push(dict(type='write',sequence=2,data='person',typed=True))
            await until(lambda:sum(f['type']=='ack' for f in second['frames'])==2)
            rows.append(dict(name='takeover',write=await failure(agent.write('denied')),signal=await failure(agent.signal('interrupt')),close=await failure(agent.close())))
            record('exclusive',terminal,handle,released,views)
            await first['close']();await second['close']();record('detached',terminal,handle,released,views)
            terminal.rename('renamed');mark=terminal.markScreen();await terminal.screen.drain()
            handle.output.push(b'new\r\nline');await until(lambda:terminal.sequence==3)
            rows.append(dict(name='mark',page=terminal.readScreen(dict(offset=0,count=100,maxBytes=1000)),mark=mark.lines()))
            handle.done.set_result(dict(exitCode=7,signal=None));await handle.output.aclose();await terminal.drained
            third=await attach(terminal);views.append(third)
            third['channel'].push(dict(type='write',sequence=1,data='exited'));await until(lambda:any(f['type']=='ack' for f in third['frames']))
            record('exit-reconnect',terminal,handle,released,views)
            await terminal.close();await third['pump'];record('closed',terminal,handle,released,views)
            try:mark.lines()
            except Exception as error:rows.append(dict(name='released-mark',code=error.code,message=str(error)))
        finally:
            for view in views:await view['close']()
            await terminal.dispose()
        for name,command in [('gap',dict(type='write',sequence=2,data='x')),('bytes',dict(type='write',sequence=1,data='中'*5)),('resize',dict(type='resize',sequence=1,cols=1,rows=2))]:
            terminal,handle,released=await fixture();view=await attach(terminal)
            try:
                view['channel'].push(command);await view['pump'];record(name,terminal,handle,released,[view])
            finally:await view['close']();await terminal.dispose()
        terminal,handle,released=await fixture();view=await attach(terminal);handle.retry=True
        try:
            rows.append(dict(name='retry-first',error=(await failure(terminal.close()))['message'],released=terminal.screenReleased))
            await terminal.close();await view['pump'];record('retry-closed',terminal,handle,released,[view])
        finally:await view['close']();await terminal.dispose()
        terminal,handle,released=await fixture()
        try:
            abort=AbortController();reason=RuntimeError('exact abort');waiting=asyncio.ensure_future(terminal.changed(terminal.revision,abort.signal));await asyncio.sleep(0);abort.abort(reason)
            try:await waiting
            except Exception as error:rows.append(dict(name='abort-wait',same=error is reason,waiters=len(terminal.waiters)))
            handle.done.set_exception(RuntimeError('wait failed'));await handle.output.aclose();await terminal.drained
            record('failed',terminal,handle,released)
        finally:await terminal.dispose()
        rows.append(dict(name='disposed',engines=len(ctx.terminalScreens.engines),workers=len(ctx.jsRuntime._workers)))
        return rows
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_browser_terminal.mts','Original BrowserTerminal and AgentTerminalHandle versus Python owner using unchanged xterm in shipped Win7 QuickJS worker. Actual async byte streams and interruptible uplinks cover split UTF-8/BOM, reconnect snapshots, exclusive input, takeover, ack refusals, resize, marks, exit/failed outcomes, final output drainage, cleanup retry and cancellation identity. Provider is controlled, not a real PTY or Remote controller acceptance.',
        [Path(__file__).resolve(),ROOT/'dsh/api/terminal_authorized.py'])
