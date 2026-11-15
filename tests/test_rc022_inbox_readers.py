import asyncio
import pytest
from scripts.rc022_inbox_readers_probe import observe,message

@pytest.mark.asyncio
async def test_retained_readers_preserve_mutations_and_failure_identity():
    for row in await observe():
        assert row['constructorReads']==0
        if row['action']=='reader-failure':
            assert row['failures']==[True]*3 and row['eventCount']==0 and row['notifications']==[]
        elif row['action']=='lazy':
            assert row['read'] is False and row['unread']==row['after']
            assert row['after']['inbox']['seq']==-1
        else:
            assert [m['id'] for m in row['claimed']]==['step','front']
            assert [m['id'] for m in row['captured']]==['step']
            assert row['replaced'] and not row['missing'] and not row['cleared']
            assert [m['id'] for m in row['retained']['step']]==['retained']
            assert row['events'][-1]['data']['outcome']=='canceled'

@pytest.mark.asyncio
async def test_loop_awaits_one_inbox_registration_before_factory_publication(monkeypatch):
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import ToolsPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    ctx=Context();handles=[]
    try:
        for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,ToolsPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
        projections=ctx.get('sessionProjections');original=SessionProjectionRegistry.register;entered=asyncio.Event();release=asyncio.Event();calls=[]
        async def delayed(registry,definition):
            calls.append(definition['key']);entered.set();await release.wait();return await original(registry,definition)
        # Patch the method, preserving the caller's traced registration owner.
        monkeypatch.setattr(SessionProjectionRegistry,'register',delayed)
        fiber=ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]));await entered.wait()
        assert fiber.state==1
        assert ctx.get('agents')._factory is None
        release.set();await fiber
        assert calls==['modelSelection','inbox'] and fiber.state==2
        def forbidden(*args,**kwargs):raise AssertionError('Agent re-registered Inbox')
        projections.register=forbidden
        for sid in ('first','second'):
            handle=await ctx.get('agents').create(dict(sessionId=sid,options=dict(provider='mock',model='mock')));handles.append(handle)
            handle.agent.inject(message(sid))
            assert [m['id'] for m in handle.agent.inbox.nextStep]==[sid]
        for handle in handles:await handle.dispose()
        handles.clear();await fiber.dispose();assert not projections.has('inbox')
    finally:
        for handle in handles:await handle.dispose()
        await ctx.fiber.dispose()
