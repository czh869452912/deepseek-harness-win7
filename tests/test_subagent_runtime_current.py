"""Actual continuation transactions, cold epochs, and lifecycle race boundaries."""
import asyncio
import json
from pathlib import Path

import pytest

from dsh.cordis.context import Context
from dsh.core.agent_current import CurrentAgentPlugin
from dsh.core.abort import AbortController
from dsh.subagent.runtime_current import CurrentSubagentPlugin
from dsh.subagent.in_process_current import CurrentSpawnInProcess,CurrentInProcessProvider
from dsh.subagent.errors import SubagentError
from dsh.session.query_current import CurrentSqliteSessionQueryPlugin
from scripts.oracles.agent_machine_current_python import execute,ScriptAdapter
from scripts.oracles.session_format_python import decode
from scripts.oracles.generate_agent_machine_current_cases import response
from tests.test_agent_machine_current import mount


CASES=json.loads((Path(__file__).resolve().parents[1]/'scripts/oracles/subagent_runtime_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['case'])
def test_retained_v3_runtime(case):assert execute(case,decode)==case['expected']


async def mounted(tmp_path,held=False):
    ctx=await mount(tmp_path)
    await ctx.plugin(CurrentSqliteSessionQueryPlugin,dict(path=':memory:',openAt='never'))
    await ctx.plugin(CurrentSubagentPlugin);await ctx.plugin(CurrentSpawnInProcess)
    if held:ctx.get('llm').registerAdapter(['held'],ScriptAdapter(dict(script=['hang']+[response() for _ in range(12)])))
    parent=await ctx.get('agents').create(dict(sessionId='parent',agentOptions=dict(provider='held' if held else 'script',model='model')))
    return ctx,parent,ctx.get('subagents')


def spec(parent,child='worker',provider='spawn'):
    return dict(provider=provider,label=child,childId=child,signal=AbortController().signal,
                request=dict(parent=parent,prompt=[dict(type='text',text='initial')]))


async def eventually(predicate):
    async def wait():
        while not predicate():await asyncio.sleep(.001)
    await asyncio.wait_for(wait(),3)


async def closed(ctx,sid):await eventually(lambda:ctx.get('agents').get(sid) is None)


@pytest.mark.asyncio
async def test_continuation_binding_tracks_optional_agents_service():
    ctx=Context()
    try:
        await ctx.plugin(CurrentSubagentPlugin);service=ctx.get('subagents')
        assert service.continuations is None
        service.interrupt('unknown',dict(kind='user',parentSessionId='parent'))
        with pytest.raises(SubagentError,match='require the agents service'):await service.startContinuable({})
        agents=await ctx.plugin(CurrentAgentPlugin)
        assert service.continuations is not None
        first=service.continuations
        await agents.dispose()
        assert service.continuations is None and first.activations.draining
        await ctx.plugin(CurrentAgentPlugin)
        assert service.continuations is not first
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_final_flush_race_rechecks_new_work_and_captures_latest_epoch(tmp_path):
    ctx,parent,service=await mounted(tmp_path);registry=service.continuations.activations
    entered=asyncio.Event();release=asyncio.Event();original=registry.flush;seen=[];once=True
    async def flush(a):
        nonlocal once
        await original(a)
        if a.id=='worker' and once:
            once=False;entered.set();await release.wait()
    registry.flush=flush
    ctx.on('subagent/end',lambda payload:seen.append(payload))
    try:
        await service.startContinuable(spec(parent.agent));await asyncio.wait_for(entered.wait(),3)
        await service._deliver_prompt(parent.agent,'worker',[dict(type='text',text='during flush')],dict(kind='user'),AbortController().signal,'queue')
        child=ctx.get('agents').get('worker');await child.whenIdle()
        assert [e['data']['turn'] for e in child.session.events if e['type']=='turn/end']==[1,2]
        release.set();await closed(ctx,'worker')
        # Registry detach precedes terminal notification; observe settlement before the parent idle cut.
        await eventually(lambda: len(seen)==1)
        await parent.agent.whenIdle()
        assert len(seen)==1 and seen[0]['stopReason']=='completed'
        observed=await ctx.get('sessionQuery').observeSession('worker')
        try:assert len([e for e in observed.events if e['type']=='turn/end'])==2
        finally:observed.dispose()
    finally:
        release.set();await service.continuations.drain();await parent.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_parent_hold_blocks_settlement_during_child_preparation_and_releases_on_failure(tmp_path):
    ctx,parent,service=await mounted(tmp_path,True);entered=asyncio.Event();release=asyncio.Event();preparing=None
    class Delayed(CurrentInProcessProvider):
        async def prepareContinuable(self,request):
            entered.set();await release.wait();raise SubagentError('prepare rejected','PREPARE_REJECTED')
    service.registerProvider(Delayed('delayed'))
    try:
        await service.startContinuable(spec(parent.agent));worker=ctx.get('agents').get('worker')
        await eventually(lambda:any(e['type']=='request/header' for e in worker.session.events))
        preparing=asyncio.create_task(service.startContinuable(spec(worker,'grandchild','delayed')))
        await asyncio.wait_for(entered.wait(),3)
        service.interrupt('worker',dict(kind='ancestor',agent=parent.agent));await worker.whenIdle()
        assert service.continuations.activations.resident['worker'].children=={'grandchild'}
        # The watcher has an actual pending ownership hold, with no Agent activity.
        await asyncio.sleep(.01)
        assert ctx.get('agents').get('worker') is worker
        release.set()
        with pytest.raises(SubagentError,match='prepare rejected'):await preparing
        await closed(ctx,'worker')
    finally:
        release.set()
        if preparing is not None:await asyncio.gather(preparing,return_exceptions=True)
        await service.continuations.drain();await parent.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('continuable',[False,True])
async def test_catalog_append_failure_releases_child_preserves_primary_and_suppresses_notice(tmp_path,continuable):
    ctx,parent,service=await mounted(tmp_path);primary=RuntimeError('catalog rejected');edges=[];original=parent.agent.session.append
    def append(kind,*args,**kwargs):
        if kind=='subagent/catalog':raise primary
        return original(kind,*args,**kwargs)
    parent.agent.session.append=append
    ctx.on('subagent/start',lambda payload:edges.append(('start',payload)))
    ctx.on('subagent/end',lambda payload:edges.append(('end',payload)))
    try:
        with pytest.raises(RuntimeError) as caught:
            if continuable:await service.startContinuable(spec(parent.agent))
            else:await service.start('spawn',dict(parent=parent.agent,prompt=[dict(type='text',text='task')],signal=AbortController().signal))
        assert caught.value is primary
        assert [a.id for a in ctx.get('agents').list()]==['parent']
        assert not service.continuations.activations.resident
        assert not any(e['type']=='agent/inbox/spliced' for e in parent.agent.session.events)
        assert [name for name,_ in edges]==(['start','end'] if continuable else [])
    finally:await service.continuations.drain();await parent.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ancestor_interrupt_preserves_pending_input_and_uses_parent_reason(tmp_path):
    ctx,parent,service=await mounted(tmp_path,True)
    try:
        await service.startContinuable(spec(parent.agent));worker=ctx.get('agents').get('worker')
        await eventually(lambda:any(e['type']=='request/header' for e in worker.session.events))
        await service._deliver_prompt(parent.agent,'worker',[dict(type='text',text='parked')],dict(kind='user'),AbortController().signal,'queue')
        service.interrupt('worker',dict(kind='ancestor',agent=parent.agent));await worker.whenIdle()
        assert worker.inbox.nextTurn and ctx.get('agents').get('worker') is worker
        endings=[e for e in worker.session.events if e['type']=='turn/end']
        assert endings[-1]['data']['reason']==dict(kind='aborted',reason=dict(kind='parent'))
        await service.drainContinuableChildren(parent.agent,['worker','worker'])
        assert ctx.get('agents').get('worker') is None
        with pytest.raises(SubagentError):service.interrupt('parent',dict(kind='ancestor',agent=parent.agent))
    finally:await service.continuations.drain();await parent.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_handle_release_failure_withholds_output_and_still_releases_ownership(tmp_path):
    ctx,parent,service=await mounted(tmp_path,True);edges=[];streaming=asyncio.Event()
    ctx.on('subagent/end',lambda payload:edges.append(payload))
    def frame(payload):
        if payload['agent'].id=='worker' and payload['frame']['type']=='chunk' and payload['frame']['chunk']['type']=='text-delta':streaming.set()
    ctx.on('agent/assistant-stream',frame)
    try:
        await service.startContinuable(spec(parent.agent));registry=service.continuations.activations
        await asyncio.wait_for(streaming.wait(),3)
        activation=registry.resident['worker'];original=activation.handle.dispose
        async def dispose():
            await original();raise RuntimeError('release failed')
        activation.handle.dispose=dispose
        with pytest.raises(SubagentError,match='handle disposal failed'):
            await service.drainContinuableChildren(parent.agent,['worker'])
        assert not registry.resident and ctx.get('agents').get('worker') is None
        assert edges[-1]['stopReason']=='error' and 'lastAssistantMessage' not in edges[-1]
        await parent.agent.whenIdle()
        notices=[e['data'] for e in parent.agent.session.events if e['type']=='user/message' and e['data']['source']['kind']=='subagent-settled']
        assert notices and notices[-1]['content'][-1]['text']=='It left no closing message.'
    finally:await service.continuations.drain();await parent.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_scoped_drain_releases_descendants_child_first_and_closes_exact_root(tmp_path):
    ctx,parent,service=await mounted(tmp_path);edges=[]
    ctx.get('llm').registerAdapter(['nested'],ScriptAdapter(dict(script=['hang','hang']+[response() for _ in range(8)])))
    parent.agent.options.provider='nested'
    ctx.on('subagent/end',lambda payload:edges.append(payload['id']))
    try:
        await service.startContinuable(spec(parent.agent));worker=ctx.get('agents').get('worker')
        await service.startContinuable(spec(worker,'grandchild'));grand=ctx.get('agents').get('grandchild')
        await eventually(lambda:any(e['type']=='request/header' for e in grand.session.events))
        await service.drainContinuableDescendants([parent.agent])
        assert edges==['grandchild','worker']
        assert not service.continuations.activations.resident
        assert ctx.get('agents').get('parent') is parent.agent and parent.agent.status=='idle'
        assert parent.agent.inbox.nextStep
        with pytest.raises(SubagentError) as caught:await service.startContinuable(spec(parent.agent,'later'))
        assert caught.value.code=='DRAINING'
    finally:await service.continuations.drain();await parent.dispose();await ctx.fiber.dispose()
