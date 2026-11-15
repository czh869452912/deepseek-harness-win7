"""Original pinned xterm screen in the shipped Win7 JavaScript substrate."""
import asyncio
import hashlib
import json
from pathlib import Path

from dsh.cordis.service import Service
from dsh.api.terminal_screen_authorized import cursor_line_start,last_content_row,render_lines,page_lines

RESOURCE_ROOT=Path(__file__).resolve().parents[1]/'javascript/terminal-screen'
MANIFEST_SHA256='36f9b9fc6ab744a7750e0821ba4510e17234d00314d75dda6f62c39f0edc33a6'


def resources():
    data=(RESOURCE_ROOT/'manifest.json').read_bytes()
    if hashlib.sha256(data).hexdigest()!=MANIFEST_SHA256:raise RuntimeError('Terminal screen manifest differs')
    manifest=json.loads(data.decode('utf-8'));result={}
    for name,record in manifest['resources'].items():
        if Path(name).name!=name or ':' in name:raise RuntimeError('Invalid terminal screen resource path')
        data=(RESOURCE_ROOT/name).read_bytes()
        if len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256']:raise RuntimeError('Terminal screen resource differs: '+name)
        result[name]=data.decode('utf-8')
    return result


def consume(task):
    if not task.cancelled():task.exception()


class ScreenMark:
    def __init__(self, screen, identity):
        self.screen,self.identity=screen,identity;self.state=dict(type=screen.buffer['type'],
            present=screen.buffer['type']=='normal',line=cursor_line_start(screen.buffer),disposed=False)

    def lines(self):
        self.screen.require_open();buffer=self.screen.buffer;end=last_content_row(buffer)+1;state=self.state
        if state['type']!=buffer['type'] or not state['present']:return dict(lines=render_lines(buffer,0,end),truncated=False)
        if state['disposed']:return dict(lines=render_lines(buffer,0,end),truncated=True)
        return dict(lines=render_lines(buffer,state['line'],end),truncated=False)

    def dispose(self):
        if self.screen.marks.pop(self.identity,None) is not None and not self.screen.closed:
            self.state=dict(self.state,disposed=True)
            self.screen.enqueue('unmark',marker=self.identity)


class TerminalScreen:
    def __init__(self,released=lambda screen:None):
        self.worker=None;self.closed=False;self.tail=None;self.closing=None
        self.released=released
        self.buffer=None;self.marks={};self.pending={};self.sequence=0;self.marker_sequence=0
        self.initialized=asyncio.get_running_loop().create_future()

    def require_open(self):
        if self.closed:raise RuntimeError('Terminal screen was closed')

    def update(self,message):
        self.buffer=message['buffer']
        for value in message['markers']:
            mark=self.marks.get(value['id'])
            if mark is not None:mark.state=value

    def observe(self,message):
        if message['type']=='screen-state':
            self.update(message)
            if not self.initialized.done():self.initialized.set_result(None)
        elif message['type']=='screen-result':
            future=self.pending.get(message['request'])
            if future is None:return
            if 'error' in message:
                if not future.done():future.set_exception(RuntimeError(message['error']))
            else:
                self.update(message)
                if not future.done():future.set_result(message)

    def worker_ended(self,settled):
        failure=settled.exception() if not settled.cancelled() else None
        error=failure or RuntimeError('Terminal screen worker ended')
        for future in [self.initialized]+list(self.pending.values()):
            if not future.done():future.set_exception(error)

    def enqueue(self,operation,**arguments):
        previous=self.tail
        async def apply():
            if previous is not None:
                try:await asyncio.shield(previous)
                except Exception:pass
            self.require_open();self.sequence+=1;identity=self.sequence
            future=asyncio.get_running_loop().create_future();self.pending[identity]=future
            try:
                await self.worker.send(dict(type='screen',operation=operation,request=identity,**arguments))
                return await asyncio.shield(future)
            finally:self.pending.pop(identity,None)
        self.tail=asyncio.ensure_future(apply());self.tail.add_done_callback(consume);return self.tail

    async def write(self,data):await asyncio.shield(self.enqueue('write',data=data))
    async def resize(self,cols,rows):await asyncio.shield(self.enqueue('resize',cols=cols,rows=rows))
    async def snapshot(self):return (await asyncio.shield(self.enqueue('snapshot')))['snapshot']

    async def drain(self):
        if self.tail is not None:await asyncio.shield(self.tail)

    def read(self,request):
        self.require_open();return page_lines(render_lines(self.buffer,0,last_content_row(self.buffer)+1),request)

    def mark(self):
        self.require_open();self.marker_sequence+=1;mark=ScreenMark(self,self.marker_sequence)
        self.marks[mark.identity]=mark;self.enqueue('mark',marker=mark.identity);return mark

    def dispose(self):
        if self.closing is None:
            self.closed=True
            async def close():
                if self.tail is not None:
                    try:await asyncio.shield(self.tail)
                    except Exception:pass
                try:
                    if self.worker is not None:await self.worker.dispose()
                finally:
                    if self.worker is not None and self.worker.process.returncode is None:await self.worker.terminate()
                    self.marks.clear();self.buffer=None;self.released(self)
            self.closing=asyncio.ensure_future(close());self.closing.add_done_callback(consume)
        return asyncio.shield(self.closing)


class TerminalScreenRuntime(Service):
    inject=['jsRuntime']

    def __init__(self,ctx,config=None):
        super().__init__(ctx,'terminalScreens');self.engines=set();self.creating=set();self.closed=False
        ctx.effect(lambda:self.dispose,'terminal screen workers')

    async def open(self,options):
        if self.closed:raise RuntimeError('Terminal screen runtime disposed')
        async def create():
            screen=TerminalScreen(self.engines.discard);assets=resources()
            try:
                screen.worker=await self.ctx.get('jsRuntime').open(dict(name='terminal-screen',body='',deferScript=True,
                    errorPrelude='',bootstrap=assets['driver.js'],headless=assets['headless.js'],serializer=assets['serialize.js'],options=options),screen.observe)
                screen.worker.result.add_done_callback(screen.worker_ended)
                await screen.worker.send(dict(type='go'));await asyncio.shield(screen.initialized)
                if self.closed:raise RuntimeError('Terminal screen runtime disposed during creation')
                self.engines.add(screen);return screen
            except BaseException:
                await screen.dispose();raise
        task=asyncio.ensure_future(create());self.creating.add(task);task.add_done_callback(self.creating.discard);task.add_done_callback(consume)
        try:return await asyncio.shield(task)
        except BaseException:
            try:screen=await asyncio.shield(task)
            except BaseException:pass
            else:await screen.dispose();self.engines.discard(screen)
            raise

    async def dispose(self):
        self.closed=True
        if self.creating:await asyncio.gather(*list(self.creating),return_exceptions=True)
        if self.engines:await asyncio.gather(*(screen.dispose() for screen in self.engines))
        self.engines.clear()
