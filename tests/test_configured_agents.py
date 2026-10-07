"""Configured Agent startup/reload derived from config-session-id.spec.ts."""
from dsh.llm.llm_service import LlmRuntime
import asyncio
import re
import pytest
from dsh.cordis.context import Context
from dsh.cordis.schema import ValidationError
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin, CONFIGURED_AGENT_IDENTITIES_KEY
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.core.session import SessionPlugin, SessionHeader
from dsh.core.session.preparation import SessionPreparation
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin

async def core(tmp_path=None, llm=None):
    ctx=Context()
    if llm is None:
        await ctx.plugin(LlmRuntime)
    else:
        ctx.provide('llm', llm)
    await ctx.plugin(SystemPrompt); await ctx.plugin(ToolsPlugin)
    await ctx.plugin(SessionPlugin); await ctx.plugin(AgentPlugin)
    if tmp_path is not None: await ctx.plugin(JsonlSessionPersistencePlugin, {'root':str(tmp_path)})
    return ctx

async def settled(predicate):
    async def poll():
        while not predicate(): await asyncio.sleep(0)
    await asyncio.wait_for(poll(),2)

async def seed(ctx, sid='saved'):
    p=ctx.get('sessionPersistence');await p.create(SessionHeader(sid))
    await p.append(sid,[dict(type='turn/start',seq=0,time=1,data={'turn':1}),dict(type='turn/end',seq=1,time=2,data={'turn':1,'reason':{'kind':'completed'}})])

@pytest.mark.asyncio
async def test_launcher_identities_override_both_keys():
    ctx=await core();ctx.provide(CONFIGURED_AGENT_IDENTITIES_KEY,{'a':{'id':'launcher','resume':False},'b':{'id':'saved','resume':True}})
    try:
        await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'a','sessionId':'ignored'}, {'id':'b','sessionId':'also-ignored'}, {'id':'c','sessionId':'untouched'}]})
        assert ctx.get('agents').get('launcher') is not None
        assert ctx.get('agents').get('untouched') is not None
        assert ctx.get('agents').get('saved') is None
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
@pytest.mark.parametrize('rows,match,exception',[
    ([{'id':'a','sessionId':''}],'string length',ValidationError),
    ([{'id':'a','sessionId':'s','resumeSessionId':'old'}],'mutually exclusive',ValueError),
    ([{'id':'a','sessionId':'s'},{'id':'b','resumeSessionId':'s'}],'duplicate exact',ValueError),
    ([{'id':'a','maxTokens':True}],'expected number but got true',ValidationError),
])
async def test_invalid_config_never_publishes(rows,match,exception):
    ctx=await core()
    seen=[];ctx.on('agent/created',lambda *args:seen.append(True))
    try:
        with pytest.raises(exception,match=match):await ctx.plugin(AgentLoopPlugin,{'agents':rows})
        assert seen==[]
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_fresh_config_ids_are_restart_safe():
    ctx=await core();ids=[]
    try:
        for _ in range(2):
            fiber=await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'cfg'}]})
            factory=ctx.get('agentLoop');agent=next(iter(factory._transactions)).agent
            ids.append(agent.id);assert re.fullmatch('cfg-session-[0-9a-f-]{36}',agent.id)
            await fiber.dispose()
        assert ids[0]!=ids[1]
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_exact_id_reload_preserves_history(tmp_path):
    ctx=await core(tmp_path);config={'agents':[{'id':'main','sessionId':'s'}]}
    try:
        first=await ctx.plugin(AgentLoopPlugin,config);await settled(lambda:ctx.get('agents').get('s'))
        old=ctx.get('agents').get('s');old.session.append('session/title',{'title':'remember'})
        await old.session.flush();await first.dispose()
        second=await ctx.plugin(AgentLoopPlugin,config);await settled(lambda:ctx.get('agents').get('s'))
        new=ctx.get('agents').get('s');assert new is not old
        assert any(e['data']=={'title':'remember'} for e in new.session.events)
        await second.dispose()
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
@pytest.mark.parametrize('cancel',[False,True])
async def test_overlap_waits_for_draining_scope_and_can_cancel(tmp_path,cancel):
    ctx=await core(tmp_path);config={'agents':[{'id':'main','sessionId':'s'}]}
    gate=asyncio.Event();entered=asyncio.Event()
    try:
        first=await ctx.plugin(AgentLoopPlugin,config);await settled(lambda:ctx.get('agents').get('s'))
        old=ctx.get('agents').get('s');old.session.append('session/title',{'title':'saved'});await old.session.flush()
        async def cleanup(): entered.set();await gate.wait()
        old.ctx.disposable(cleanup)
        disposal=asyncio.ensure_future(first.dispose());await asyncio.wait_for(entered.wait(),2)
        second=await ctx.plugin(AgentLoopPlugin,config)
        await asyncio.sleep(0);assert ctx.get('agents').get('s') is old
        if cancel: await asyncio.wait_for(second.dispose(),2)
        gate.set();await disposal
        if cancel: assert ctx.get('agents').get('s') is None
        else:
            await settled(lambda:ctx.get('agents').get('s'))
            assert ctx.get('agents').get('s') is not old
            assert ctx.get('agents')._factory is not None
            await second.dispose()
    finally: gate.set();await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_deferred_resume_is_owned_and_starts_when_storage_arrives(tmp_path):
    ctx=await core()
    try:
        fiber=await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'main','resumeSessionId':'saved'}]})
        effect=next(e for e in fiber.get_effects() if e['label']=='agentLoop.resume(main)')
        assert [c['label'] for c in effect['children']]==['ctx.plugin()']
        # A real artifact is created before the delayed provider is published.
        from dsh.session.persistence_jsonl import JsonlSessionPersistence
        p=JsonlSessionPersistence(str(tmp_path));await p.create(SessionHeader('saved'))
        await p.append('saved',[dict(type='session/end-seed',seq=0,time=1,data={})])
        await ctx.plugin(JsonlSessionPersistencePlugin,{'root':str(tmp_path)})
        await settled(lambda:ctx.get('agents').get('saved'))
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
@pytest.mark.parametrize('unrenderable',[False,True])
async def test_index_and_observer_failures_are_contained(tmp_path,unrenderable):
    ctx=await core(tmp_path);seen=[];warnings=[]
    class Unrenderable(Exception):
        def __str__(self):raise RuntimeError('coercion escaped')
    failure=Unrenderable() if unrenderable else ValueError('index failed')
    if not unrenderable: failure.__cause__=OSError('persistence unavailable')
    async def fail():raise failure
    ctx.get('sessionPersistence').list=fail
    def observer(*args):raise failure
    async def async_observer(*args):raise failure
    ctx.on('agent-loop/config-start-failed',observer);ctx.on('agent-loop/config-start-failed',async_observer)
    ctx.on('agent-loop/config-start-failed',lambda value:seen.append(value))
    ctx.logger.warn=lambda message,*args:warnings.append(message)
    try:
        await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'main','sessionId':'s'}]})
        await settled(lambda:len(warnings)==3)
        assert seen==[{'sessionId':'s','error':failure}]
        assert ctx.get('agents').get('s') is None
        assert all(('<unrenderable value>' if unrenderable else 'index failed') in message for message in warnings)
        if not unrenderable:
            assert all('index failed: persistence unavailable' in message for message in warnings)
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
@pytest.mark.parametrize('late_success',[False,True])
async def test_disposal_abandons_preparation_and_suppresses_reports(tmp_path,late_success):
    ctx=await core(tmp_path);entered=asyncio.Event();pending=asyncio.get_running_loop().create_future();released=[];failures=[]
    async def prepare(*args):entered.set();return await pending
    ctx.get('sessionPersistence').prepare=prepare
    ctx.on('agent-loop/config-start-failed',lambda value:failures.append(value))
    try:
        fiber=await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'main','sessionId':'s'}]})
        await asyncio.wait_for(entered.wait(),2);await asyncio.wait_for(fiber.dispose(),2)
        if late_success:
            pending.set_result(SessionPreparation.create(ctx.get('sessions').prepare('s'),{'release':lambda:released.append(True)}))
            await settled(lambda:released)
            assert released==[True]
        else:
            pending.set_exception(ValueError('late failure'));await asyncio.sleep(0);await asyncio.sleep(0)
        assert failures==[] and ctx.get('agents').get('s') is None
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_missing_explicit_resume_does_not_create(tmp_path):
    ctx=await core(tmp_path);failures=[];ctx.on('agent-loop/config-start-failed',lambda value:failures.append(value))
    try:
        await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'main','resumeSessionId':'missing'}]})
        await settled(lambda:failures)
        assert ctx.get('agents').get('missing') is None
        assert await ctx.get('sessionPersistence').list()==[]
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_disposal_does_not_wait_for_hung_index(tmp_path):
    ctx=await core(tmp_path);pending=asyncio.get_running_loop().create_future();entered=asyncio.Event();failures=[]
    async def listing():entered.set();return await pending
    ctx.get('sessionPersistence').list=listing
    ctx.on('agent-loop/config-start-failed',lambda value:failures.append(value))
    try:
        fiber=await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'a','sessionId':'s'}]})
        await asyncio.wait_for(entered.wait(),2)
        await asyncio.wait_for(fiber.dispose(),2)
        pending.set_exception(ValueError('late index failure'))
        await asyncio.sleep(0);await asyncio.sleep(0)
        assert failures==[] and ctx.get('agents').get('s') is None
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_configured_reload_continues_real_driver_history(tmp_path):
    import json
    from test_e2e_core_spine_strict_parity import StrictMockLlmAdapter
    adapter=StrictMockLlmAdapter([{'text':'Remember 42.'},{'text':'The earlier answer was 42.'}])
    ctx=await core(tmp_path, llm=adapter)
    config={'agents':[{'id':'main','sessionId':'s','provider':'mock','model':'mock'}]}
    try:
        first=await ctx.plugin(AgentLoopPlugin,config);await settled(lambda:ctx.get('agents').get('s'))
        old=ctx.get('agents').get('s');old.followup('Remember 42');await old.when_idle();await old.session.flush();await first.dispose()
        second=await ctx.plugin(AgentLoopPlugin,config);await settled(lambda:ctx.get('agents').get('s'))
        new=ctx.get('agents').get('s');new.followup('What was the number?');await new.when_idle();await new.session.flush()
        assert len(adapter.requests)==2 and '42' in json.dumps(adapter.requests[-1])
        stored=await ctx.get('sessionPersistence').load('s')
        assert len([e for e in stored.events if e['type']=='turn/start'])==2
        await second.dispose()
    finally:await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_hanging_failure_observer_cannot_block_factory_disposal(tmp_path):
    ctx=await core(tmp_path);entered=asyncio.Event();pending=asyncio.get_running_loop().create_future()
    async def listener(value):entered.set();await pending
    ctx.on('agent-loop/config-start-failed',listener)
    try:
        fiber=await ctx.plugin(AgentLoopPlugin,{'agents':[{'id':'main','resumeSessionId':'missing'}]})
        await asyncio.wait_for(entered.wait(),2)
        await asyncio.wait_for(fiber.dispose(),2)
        pending.set_exception(ValueError('late observer failure'))
        await asyncio.sleep(0);await asyncio.sleep(0)
        assert ctx.get('agents').get('missing') is None
    finally:
        if not pending.done():pending.set_result(None)
        await ctx.fiber.dispose()
