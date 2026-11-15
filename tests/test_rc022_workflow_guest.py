import asyncio
import os
from types import SimpleNamespace

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.javascript.runtime import JavaScriptRuntime
from dsh.workflow.ptc_executor import QuickJsWorkflowExecutor
from dsh.workflow.ptc_run import PtcWorkflowRun
from scripts.rc022_workflow_guest_probe import observe

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Native private VM worker targets Windows')


def test_manifest_tampering_is_rejected(tmp_path,monkeypatch):
    import dsh.workflow.ptc_executor as executor
    (tmp_path/'resources.json').write_text('{}',encoding='utf-8')
    monkeypatch.setattr(executor,'ASSETS',tmp_path)
    with pytest.raises(ValueError,match='manifest differs'):executor.bootstrap()


@pytest.mark.asyncio
async def test_original_guest_on_private_native_vm():
    rows={row['name']:row for row in await observe()}
    assert all(row['workers']==0 for row in rows.values())
    assert rows['value']['result']['value']==dict(answer=42,missing=None)
    assert rows['realm']['result']['value']==['undefined']*6
    assert rows['structured-child']['result']['value']==dict(ok=True)
    assert rows['parallel']['result']['value']==['reply:one','reply:two','reply:three']
    assert rows['parallel']['maxActive']==2
    assert rows['parallel']['closed']==[1,2,3]
    assert rows['caught']['result']['value']==[None,7]
    assert len(rows['progress-drain']['events'])==100
    assert rows['sync-timeout']['result']['stopReason']=='error'
    assert rows['syntax']['result']['stopReason']=='error'


@pytest.mark.asyncio
@pytest.mark.parametrize('late',[False,True])
async def test_abort_real_guest_joins_late_start_and_native_worker(late):
    ctx=Context();await ctx.plugin(JavaScriptRuntime)
    entered=asyncio.Event();release=asyncio.Event();disposed=[];external=AbortController()
    async def ensure(*_):return 'C:/fixed'
    ctx.set_service('workingDirectory',SimpleNamespace(ensure=ensure))
    async def start(spec):
        entered.set()
        if late:await release.wait()
        async def dispose():disposed.append('child')
        return dict(childId='child',result=asyncio.get_event_loop().create_future(),dispose=dispose)
    observer=SimpleNamespace(phase=lambda _:None,log=lambda _:None,agentStart=lambda _:None,agentEnd=lambda _:None)
    init=dict(meta=dict(name='abort',description='real child ownership'),body="return await agent('task')",limits=dict(maxConcurrentAgents=1,maxTotalAgents=3,maxItemsPerCall=10,syncTimeoutMs=1000))
    run=PtcWorkflowRun(ctx,SimpleNamespace(startActivation=start),QuickJsWorkflowExecutor(ctx.jsRuntime),'run',init['meta'],None,init,'stub',dict(mode='read-only'),observer,external.signal)
    try:
        await asyncio.wait_for(entered.wait(),5)
        external.abort('external');disposal=run.dispose()
        if late:
            await asyncio.sleep(.02);assert not disposal.task.done();release.set()
        await asyncio.wait_for(disposal,5)
        assert (await run.result)['stopReason']=='cancelled'
        assert disposed==['child'] and not ctx.jsRuntime._workers
        assert not run.children and not run.pending and not external.signal._listeners
    finally:
        release.set();await run.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_real_guest_actual_v4_spawn_activation_and_directory(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from scripts.oracles.generate_agent_machine_current_cases import response
    fixture=await setup(tmp_path/'sessions',script=[response('actual child')],directory=tmp_path)
    ctx=fixture.ctx;await ctx.plugin(JavaScriptRuntime)
    handle=await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model')))
    parent=handle.agent;events=[]
    observer=SimpleNamespace(phase=lambda _:None,log=lambda _:None,agentStart=lambda info:events.append(('start',info)),agentEnd=lambda info:events.append(('end',info)))
    init=dict(meta=dict(name='actual',description='spawn'),body="return await agent('task')",limits=dict(maxConcurrentAgents=1,maxTotalAgents=3,maxItemsPerCall=10,syncTimeoutMs=1000))
    run=PtcWorkflowRun(ctx,ctx.subagents,QuickJsWorkflowExecutor(ctx.jsRuntime),'run',init['meta'],parent,init,'spawn',dict(mode='read-only'),observer)
    try:
        result=await asyncio.wait_for(asyncio.shield(run.result),10)
        assert result==dict(value='actual child',stopReason='completed',agentsStarted=1)
        assert [item[0] for item in events]==['start','end']
        child_id=events[0][1]['childId'];assert ctx.agents.get(child_id) is None
        stored=await ctx.sessionQuery.readSession(child_id)
        changes=[event['data']['cwd'] for event in stored['events'] if event['type']=='working-directory/change']
        assert changes==[str(tmp_path)]
        assert not ctx.jsRuntime._workers
    finally:await run.dispose();await ctx.fiber.dispose()
