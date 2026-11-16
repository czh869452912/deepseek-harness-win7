import asyncio
import hashlib
import json
from types import SimpleNamespace as NS

import pytest
import pytest_asyncio

from dsh.api.workspace_changes_022 import WorkspaceChangeFeed
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.typert.remote import RemoteError
from test_rc022_workspace_preview import setup


class FileSystem:
    def __init__(self):self.info=NS(type='file',version='current');self.callbacks=[];self.watches=[];self.closes=0;self.stats=[]
    async def resolve(self,path,options):return NS(targetKey=path if path.startswith('/') else '/workspace/'+path,displayPath=path)
    async def stat(self,target,signal):self.stats.append(target.targetKey);return self.info
    def contains(self,root,target):return target.targetKey==root.targetKey or target.targetKey.startswith(root.targetKey+'/')
    def processPath(self,target):return target.targetKey
    async def watch(self,target,changed,signal):
        self.callbacks.append(changed);self.watches.append((target,signal))
        async def close():self.closes+=1
        return close


@pytest_asyncio.fixture
async def controlled():
    ctx=Context();fs=FileSystem();ctx.set_service('fs',fs);feed=WorkspaceChangeFeed(ctx);streams=[];controllers=[];tasks=[];gates=[]
    def open(path='target',controller=None):
        controller=controller or AbortController();controllers.append(controller);stream=feed.follow('/workspace',path,controller.signal);streams.append(stream);return stream,controller
    def start(stream):task=asyncio.create_task(stream.__anext__());tasks.append(task);return task
    def gate():value=asyncio.Event();gates.append(value);return value
    yield NS(ctx=ctx,fs=fs,feed=feed,open=open,start=start,gate=gate)
    for controller in controllers:controller.abort()
    for value in gates:value.set()
    await asyncio.gather(*tasks,return_exceptions=True)
    await asyncio.gather(*(stream.aclose() for stream in streams),return_exceptions=True)
    await ctx.fiber.dispose()


async def next_frame(stream):return await asyncio.wait_for(stream.__anext__(),2)


@pytest.mark.asyncio
async def test_ready_waits_for_root_and_watch_then_restats_queued_observations(controlled):
    c=controlled;root_entered=c.gate();root_release=c.gate();watch_entered=c.gate();watch_release=c.gate();resolve=c.fs.resolve;watch=c.fs.watch
    async def resolving(path,options):
        if path=='/workspace':root_entered.set();await root_release.wait()
        return await resolve(path,options)
    async def watching(*args):watch_entered.set();await watch_release.wait();return await watch(*args)
    c.fs.resolve=resolving;c.fs.watch=watching;stream,_=c.open();first=c.start(stream);await root_entered.wait()
    target=NS(targetKey='/workspace/target',displayPath='other')
    c.ctx.emit('fs/observed',target,dict(kind='absent'));assert not first.done() and not c.fs.watches
    root_release.set();await watch_entered.wait();c.ctx.emit('fs/observed',target,dict(kind='present',version='stale'));assert not first.done()
    watch_release.set();assert await first==dict(kind='ready')
    for version in ('new1','new2'):
        c.fs.info=NS(type='file',version=version)
        assert await next_frame(stream)==dict(kind='change',change=dict(absolutePath='/workspace/target',version=version))


@pytest.mark.asyncio
async def test_target_keys_filter_before_stat_and_absence_is_current_metadata(controlled):
    c=controlled;stream,_=c.open();assert await next_frame(stream)==dict(kind='ready');pending=c.start(stream);c.fs.stats.clear()
    c.ctx.emit('fs/observed',NS(targetKey='/other',displayPath='/workspace/target'),dict(kind='present',version='stale'))
    c.ctx.emit('fs/observed',NS(targetKey='/workspace/target',displayPath='other'),dict(kind='present',version='stale'));c.fs.info=None
    assert await pending==dict(kind='change',change=dict(absolutePath='/workspace/target',absent=True))
    assert c.fs.stats==['/workspace/target']


@pytest.mark.asyncio
async def test_separate_generations_and_paused_cancel_drop_queued_items(controlled):
    c=controlled;one,controller=c.open();two,_=c.open();await next_frame(one);await next_frame(two)
    c.fs.callbacks[0]();controller.abort();await asyncio.sleep(0)
    with pytest.raises(StopAsyncIteration):await next_frame(one)
    assert c.fs.closes==1;c.fs.callbacks[1]();assert (await next_frame(two))['kind']=='change';assert len(c.feed.followers)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('phase',['root','target','watch','initial-stat','change-stat'])
@pytest.mark.parametrize('reject',[False,True])
async def test_cancel_during_setup_or_stat_has_no_late_ready_or_change(controlled,phase,reject):
    c=controlled;entered=c.gate();release=c.gate();stream,controller=c.open()
    if phase=='change-stat':await next_frame(stream)
    async def block(signal):
        entered.set();await release.wait()
        if reject:signal.throwIfAborted()
    if phase in ('root','target'):
        original=c.fs.resolve
        async def resolve(path,options):
            if (path=='/workspace')==(phase=='root'):await block(options['signal'])
            return await original(path,options)
        c.fs.resolve=resolve
    elif phase=='watch':
        original=c.fs.watch
        async def watch(target,changed,signal):await block(signal);return await original(target,changed,signal)
        c.fs.watch=watch
    else:
        original=c.fs.stat
        async def stat(target,signal):await block(signal);return await original(target,signal)
        c.fs.stat=stat
    pending=c.start(stream)
    if phase=='change-stat':c.fs.callbacks[0]()
    await entered.wait();controller.abort();release.set()
    with pytest.raises(StopAsyncIteration):await pending
    assert c.fs.closes==(1 if phase=='change-stat' or phase=='watch' and not reject else 0)
    assert not c.feed.followers and not controller.signal._listeners


@pytest.mark.asyncio
@pytest.mark.parametrize('when',['before','after'])
async def test_callback_failure_keeps_exact_error_and_awaits_close(controlled,when):
    c=controlled;failure=RuntimeError('watch failed');entered=c.gate();release=c.gate()
    async def watch(target,changed,signal):
        c.fs.callbacks.append(changed)
        if when=='before':changed(failure)
        async def close():c.fs.closes+=1;entered.set();await release.wait()
        return close
    c.fs.watch=watch;stream,_=c.open()
    if when=='after':await next_frame(stream)
    pending=c.start(stream)
    if when=='after':c.fs.callbacks[0](failure)
    await entered.wait();assert not pending.done();release.set()
    with pytest.raises(Exception) as error:await pending
    if when=='after':assert error.value is failure
    else:assert error.value.code=='workspace-file/watch-unsupported' and error.value.message=='watch failed'
    assert c.fs.closes==1 and not c.feed.followers


@pytest.mark.asyncio
async def test_outside_directory_is_rechecked_but_outside_files_can_watch(controlled):
    c=controlled;c.fs.info=NS(type='directory',version='dir');stream,_=c.open('/outside')
    with pytest.raises(RemoteError) as error:await next_frame(stream)
    assert error.value.code=='workspace-file/outside-workspace' and not c.fs.watches
    c.fs.info=NS(type='file',version='file');stream,_=c.open('/outside');await next_frame(stream)
    c.fs.info=NS(type='directory',version='dir');c.fs.callbacks[0]()
    with pytest.raises(RemoteError) as error:await next_frame(stream)
    assert error.value.code=='workspace-file/outside-workspace' and c.fs.closes==1


@pytest.mark.asyncio
async def test_disposal_while_paused_awaits_each_close(controlled):
    c=controlled;entered=c.gate();release=c.gate();original=c.fs.watch
    async def watch(*args):
        close=await original(*args)
        async def blocked():await close();entered.set();await release.wait()
        return blocked
    c.fs.watch=watch;streams=[c.open()[0] for _ in range(2)]
    for stream in streams:await next_frame(stream)
    disposal=asyncio.create_task(c.feed.close());await entered.wait();await asyncio.sleep(0);assert not disposal.done()
    release.set();await disposal;assert c.fs.closes==2 and not c.feed.followers
    for stream in streams:
        with pytest.raises(StopAsyncIteration):await next_frame(stream)


@pytest.mark.asyncio
async def test_preabort_does_not_acquire_and_resolution_errors_keep_identity(controlled):
    c=controlled;controller=AbortController();failure=RuntimeError('cancel');controller.abort(failure);stream,_=c.open(controller=controller)
    with pytest.raises(RuntimeError) as error:await next_frame(stream)
    assert error.value is failure and not c.fs.watches and not c.feed.followers
    async def resolve(*_):raise failure
    c.fs.resolve=resolve;stream,_=c.open()
    with pytest.raises(RuntimeError) as error:await next_frame(stream)
    assert error.value is failure and not c.feed.followers


@pytest.mark.asyncio
async def test_actual_native_watcher_sees_uninstrumented_changes_and_releases(tmp_path):
    ctx=await setup(tmp_path);controller=AbortController();stream=ctx.workspaceFiles.changes(dict(workspaceRoot=str(tmp_path)),'new.txt',controller.signal)
    try:
        assert await next_frame(stream)==dict(kind='ready');assert len(ctx.fs.watchers)==1
        (tmp_path/'new.txt').write_bytes(b'created')
        change=await next_frame(stream);assert change['kind']=='change' and 'version' in change['change']
        assert change['change']['absolutePath']==str(tmp_path/'new.txt')
        (tmp_path/'new.txt').unlink();assert (await next_frame(stream))['change']['absent']
        controller.abort()
        with pytest.raises(StopAsyncIteration):await next_frame(stream)
        assert not ctx.fs.watchers
    finally:controller.abort();await stream.aclose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_generated_target_watch_mux_admission_cancel_and_peer_close(tmp_path):
    from test_rc022_workspace_preview import ARTIFACT,Response
    from scripts.rc022_duplex_mux_probe import Client
    from dsh.host.webserver.webserver import WebServerService
    from dsh.host.connection.auth_current import CurrentBrowserAuth
    from dsh.host.connection.authorized import AuthorizedHostConnection
    from dsh.typert.artifact import read_generated_artifact
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_authorized import AuthorizedGatewayService
    if not ARTIFACT.is_file():pytest.skip('actual pinned workspace artifact required')
    ctx=await setup(tmp_path);server=WebServerService(ctx,host='127.0.0.1',port=0);ctx.set_service('webServer',server)
    auth=CurrentBrowserAuth(ctx,bytes(range(32)),1);connection=AuthorizedHostConnection(ctx,[],auth);ctx.set_service('connection',connection)
    ctx.set_service('appReady',NS(onReady=lambda callback:callback()));await ctx.plugin(RemoteAccessService)
    await ctx.plugin(AuthorizedGatewayService,dict(websocketCompression='none'));ctx.typert.register(read_generated_artifact(ARTIFACT))
    await server.start();response=Response();connection.authorize_connect(dict(method='GET',headers=dict(host='127.0.0.1:'+str(server.listened_port)),raw_url='/connect?token='+auth.launch_token),response)
    cookie=response.state['headers']['set-cookie'].split(';')[0];client=None;frames=[]
    async def receive():frame=await client.receive();frames.append(frame);return frame
    async def open(key,**args):await client.send(dict(type='open',streamId=key,endpoint='workspaceFiles/changes',payload=dict(args=dict(dict(workspaceFileScopeId='session',path='new.txt'),**args))))
    async def released():
        while ctx.fs.watchers:await asyncio.sleep(.01)
    try:
        client=await Client().connect(server.listened_port,cookie=cookie)
        await open('watch');assert await receive()==dict(type='item',streamId='watch',value=dict(kind='ready'))
        assert len(ctx.fs.watchers)==1 and ctx.get('agents') is None
        (tmp_path/'new.txt').write_bytes(b'outside edit');frame=await receive()
        assert frame['type']=='item' and frame['value']['kind']=='change' and 'version' in frame['value']['change']
        await open('invalid',path=12);frame=await receive();assert frame['type']=='error' and frame['error']['code']=='gateway/input-invalid'
        await open('missing',workspaceFileScopeId='unknown');frame=await receive();assert frame['type']=='error' and frame['error']['code']=='gateway/lookup-not-found'
        assert len(ctx.fs.watchers)==1
        await client.send(dict(type='cancel',streamId='watch'));await asyncio.wait_for(released(),3)
        await open('peer-close');assert (await receive())['value']==dict(kind='ready');assert len(ctx.fs.watchers)==1
        await client.close();client=None;await asyncio.wait_for(released(),3)
    finally:
        (tmp_path/'workspace-changes-wire-observations.json').write_text(json.dumps(dict(artifactSha256=hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(),frames=frames),indent=2),encoding='utf-8')
        if client is not None:await client.close()
        await server.stop();await ctx.fiber.dispose()
