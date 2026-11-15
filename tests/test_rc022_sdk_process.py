import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import pytest
from dsh.sdk.client import HarnessClient, create_process_deepseek_harness, resolve_dsh_launch
from dsh.sdk.errors import TransportClosedError, RequestTimeoutError, JsonRpcResponseError
from dsh.core.abort import AbortController
from dsh.subagent import sdk_run

PEER=Path(__file__).parent/'fixtures/sdk_client_runtime.py'


def runtime(workspace, **env):
    return dict(command=sys.executable,args=[str(PEER)],cwd=str(workspace),environment=lambda:dict(os.environ,**env),
        description='native test peer',initializeTimeoutMs=500,requestTimeoutMs=300,shutdownTimeoutMs=40,
        disposeEofGraceMs=40,disposeGraceMs=500)


async def until(predicate):
    deadline=asyncio.get_running_loop().time()+3
    while not predicate():
        assert asyncio.get_running_loop().time()<deadline
        await asyncio.sleep(.01)


def assert_reaped(client):
    assert client.child.poll() is not None
    assert all(stream.closed for stream in (client.child.stdin,client.child.stdout,client.child.stderr))
    assert client.monitor.done() and not client.transport.pending
    assert client.input.task.done() and client.stderr_input.task.done()


@pytest.mark.asyncio
async def test_real_sdk_client_timeout_subscriptions_and_forced_exit(tmp_path):
    client=HarnessClient(runtime=runtime(tmp_path,IGNORE_SHUTDOWN='1',IGNORE_EOF='1',STDERR='private stderr tail'))
    try:
        with pytest.raises(TransportClosedError):client.onRequest(lambda *_:None)
        assert (await client.initialize(dict(cwd=str(tmp_path),provider='p',model='m')))['serverInfo']['name']=='scripted-native-peer'
        throwing=client.subscribe(lambda _:(_ for _ in ()).throw(RuntimeError('filter failed')))
        tree=client.subscribeSessionTree('root')
        await client.request('notifications')
        assert (await tree.next())['method']=='subagent.started'
        assert (await tree.next())['params']['sessionId']=='child'
        from dsh.core.session.json import UNDEFINED
        assert tree.tryNext() is UNDEFINED
        with pytest.raises(RuntimeError,match='filter failed'):await throwing.next()
        for _ in range(3):
            with pytest.raises(RequestTimeoutError):await client.request('hang',timeoutMs=15)
            assert client.transport.pending=={}
        with pytest.raises(JsonRpcResponseError):await client.request('unknown')
        first=client.close();assert first is client.close();await first
        assert_reaped(client)
        assert 'private stderr tail' in '\n'.join(client.stderr_tail)
        with pytest.raises(TransportClosedError):await client.subscribe().next()
        with pytest.raises(TransportClosedError):await client.request('initialize')
    finally:await client.close()


@pytest.mark.asyncio
async def test_failed_initialize_reaps_and_retries_with_new_client(tmp_path):
    harness=create_process_deepseek_harness(runtime(tmp_path,FAIL_ONCE=str(tmp_path/'failed')),dict(cwd=str(tmp_path)))
    first=harness.client
    try:
        with pytest.raises(JsonRpcResponseError):await harness.start()
        assert_reaped(first)
        assert harness.client is not first
        await harness.start()
        assert await harness.session('main').getWorkingDirectory()==str(tmp_path)
    finally:await harness.close()
    assert_reaped(harness.client)


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['initialize','prompt'])
async def test_real_run_cancellation_settles_and_reaps(tmp_path,monkeypatch,stage):
    created=[];marker=tmp_path/'ready'
    env=dict(RECORD_INIT=str(marker),HANG_INIT='1') if stage=='initialize' else dict(PROMPT_READY=str(marker),HANG_PROMPT='1')
    def create(options):
        harness=create_process_deepseek_harness(runtime(tmp_path,**env),options);created.append(harness.client);return harness
    monkeypatch.setattr(sdk_run.internals,'createHarness',create)
    controller=AbortController()
    spec=dict(profile='sdk',patches=[],dshHome=str(tmp_path),cwd=str(tmp_path),provider='p',model='m',env={},
        shutdownTimeoutMs=40,disposeEofGraceMs=40,disposeGraceMs=500)
    pending=asyncio.create_task(sdk_run.start_sdk_run(dict(signal=controller.signal,prompt=[dict(type='text',text='task')]),spec))
    await until(marker.exists)
    controller.abort()
    if stage=='initialize':
        with pytest.raises(RuntimeError,match='aborted before'):await pending
    else:
        handle=await pending
        assert await asyncio.wait_for(handle.result,.5)==dict(output=[],stopReason='aborted')
        await handle.dispose()
    for client in created:assert_reaped(client)
    assert controller.signal._listeners==[]


@pytest.mark.asyncio
async def test_actual_sdk_provider_activation_route_and_unload(tmp_path,monkeypatch):
    from scripts.rc022_subagent_fixture import setup
    from dsh.subagent.sdk_provider import SubagentDshSdk
    fixture=await setup(tmp_path/'host');ctx=fixture.ctx;clients=[];records=tmp_path/'initialize.json'
    def create(options):
        harness=create_process_deepseek_harness(runtime(tmp_path,RECORD_INIT=str(records)),options);clients.append(harness.client);return harness
    monkeypatch.setattr(sdk_run.internals,'createHarness',create)
    try:
        owner=await ctx.plugin(SubagentDshSdk,dict(dshHome=str(tmp_path),provider='sdk-route',model='sdk-model',maxTokens=19))
        provider=fixture.service.providers['dsh-sdk']
        assert provider.capabilities['agentOptions'] and not provider.inheritsParentContext
        parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model')))).agent
        # Fixture workingDirectory is deliberately controlled, so use an actual
        # directory for this process consumer rather than the fixture sentinel.
        async def ensure(*_):return str(tmp_path)
        ctx.workingDirectory.ensure=ensure
        receipt=await fixture.service.startActivation(dict(provider='dsh-sdk',parent=parent,label='SDK task',prompt=[dict(type='text',text='task')],
            signal=fixture.signal,delivery='caller',agentOptions=dict(provider='override',model='model',reasoningEffort='low',maxTokens=23)))
        result=await receipt['result']
        assert result['stopReason']=='completed' and result['output']==[dict(type='text',text='wire answer')]
        await receipt['dispose']()
        handshake=json.loads(records.read_text(encoding='utf-8'))
        assert {key:handshake[key] for key in ('provider','model','reasoningEffort','maxTokens')}==dict(provider='override',model='model',reasoningEffort='low',maxTokens=23)
        for client in clients:assert_reaped(client)
        await owner.dispose()
        assert 'dsh-sdk' not in fixture.service.providers
    finally:await ctx.fiber.dispose()


def test_native_launch_resolves_profile_patch_and_explicit_environment(tmp_path):
    options=dict(dshBin='entry.py',profile='sdk',patches=['child.yml'],dshHome='home',processCwd='child',env={'EXPLICIT':'1'})
    launch=resolve_dsh_launch(options,str(tmp_path))
    assert launch['command']==sys.executable
    assert launch['args']==[str(tmp_path/'entry.py'),'--profile','sdk','--patch',str(tmp_path/'child.yml')]
    assert launch['cwd']==str(tmp_path/'child')
    assert launch['environment']()==dict(EXPLICIT='1',DSH_HOME=str(tmp_path/'home'))


@pytest.mark.asyncio
async def test_sdk_provider_configuration_and_failed_cwd_do_not_register_or_spawn(tmp_path,monkeypatch):
    from scripts.rc022_subagent_fixture import setup
    from dsh.subagent.sdk_provider import SubagentDshSdk,resolve_sdk_route
    fixture=await setup(tmp_path/'host');ctx=fixture.ctx
    def forbidden(_):raise AssertionError('must not spawn')
    monkeypatch.setattr(sdk_run.internals,'createHarness',forbidden)
    try:
        for config in [dict(dshHome='relative'),dict(dshHome=str(tmp_path),dshBin=str(tmp_path/'missing')),
                dict(dshHome=str(tmp_path),patches=[str(tmp_path)]),dict(dshHome=str(tmp_path),disposeGraceMs=0)]:
            with pytest.raises(Exception):await ctx.plugin(SubagentDshSdk,config)
            assert 'dsh-sdk' not in fixture.service.providers
        owner=await ctx.plugin(SubagentDshSdk,dict(dshHome=str(tmp_path/'not-created')))
        provider=fixture.service.providers['dsh-sdk']
        assert dict(provider.agentRouteDefaults)==dict(provider='deepseek-official',model='deepseek-v4-flash')
        parent=NS(session=NS(header=dict(cwd=str(tmp_path))))
        with pytest.raises(sdk_run.SdkRunFailure) as captured:
            await provider.start(dict(signal=fixture.signal,cwd=str(tmp_path/'missing'),parent=parent))
        assert captured.value.facts==dict(stage='initialize',category='configuration')
        assert str(tmp_path) not in str(captured.value) and str(tmp_path) in str(captured.value.cause)
        await owner.dispose()
        assert resolve_sdk_route(dict(provider='p',model='m',maxTokens=5),dict(provider=None,model='new',reasoningEffort=None))==dict(provider='p',model='new',reasoningEffort=None,maxTokens=5)
    finally:await ctx.fiber.dispose()
