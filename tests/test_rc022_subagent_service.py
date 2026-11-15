import asyncio
from types import SimpleNamespace as NS
import pytest
from scripts.rc022_subagent_service_probe import observe


@pytest.mark.asyncio
async def test_service_registration_and_dispatch_contracts():
    rows={row['action']:row for row in await observe()}
    assert rows['local']['value']==dict(kind='local')
    assert rows['external']['value']==dict(kind='external')
    assert rows['invalid-schema']['error']=='UNSUPPORTED_SCHEMA'
    assert rows['provider-change']['error']=='PROVIDER_CHANGED'
    assert not rows['added-failure']['registered']
    assert all(row['released'] and not row['remaining'] for row in rows.values())


@pytest.mark.asyncio
@pytest.mark.parametrize('backend',['spawn','fork'])
async def test_public_provider_through_real_factory_and_cold_resume(tmp_path,backend):
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.cordis.volatile import WRITE
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin
    from dsh.session.query_current import CurrentSessionQueryService
    from dsh.subagent.service import SubagentPlugin
    from dsh.subagent.providers import SpawnInProcessPlugin,ForkInProcessPlugin
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from scripts.oracles.generate_agent_machine_current_cases import response
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Projections(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    ctx=Context()
    try:
        for plugin in (CurrentLlmRuntime,Store,Projections,CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentAgentPlugin):
            await ctx.plugin(plugin)
        await ctx.plugin(CurrentJsonlSessionPersistencePlugin,dict(root=str(tmp_path),compression='none'))
        await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
        ctx.get('llm').registerAdapter(['script'],ScriptAdapter(dict(script=[response('answer') for _ in range(4)])))
        ctx.set_service('sessionQuery',CurrentSessionQueryService(ctx))
        async def ensure(agent,signal):return 'C:/rc022-work'
        async def directory(agent,path,signal):return path
        ctx.set_service('workingDirectory',NS(ensure=ensure,set=directory))
        owner=await ctx.plugin(SubagentPlugin)
        service=ctx.get('subagents')
        provider_owner=await ctx.plugin(SpawnInProcessPlugin if backend=='spawn' else ForkInProcessPlugin)
        assert service.getProvider(backend) is not None
        getattr(service.config['maxDepth'],WRITE)(3)
        assert service.resolveMaxDepth()==3
        parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model')))).agent
        parent.session.append('turn/start',dict(turn=1))
        parent.session.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
        lifecycle=[]
        ctx.on('subagent/start',lambda info:lifecycle.append(('start',info['id'],ctx.agents.get(info['id']) is not None)))
        ctx.on('subagent/end',lambda info:lifecycle.append(('end',info['id'],info['stopReason'])))
        receipt=await service.startActivation(dict(provider=backend,parent=parent,childId='child',name='worker',label='Task',
            prompt=[dict(type='text',text='task')],signal=NEVER_ABORTED,delivery='caller'))
        assert receipt['messageId']
        assert (await asyncio.wait_for(asyncio.shield(receipt['result']),5))['stopReason']=='completed'
        assert ctx.agents.get('child') is None
        assert await service.resolveName(parent,'worker',NEVER_ABORTED)=='child'
        assert (await service.listChildren('parent'))[0]['name']=='worker'
        await service.sendMessage(parent,'child',[dict(type='text',text='again')],dict(signal=NEVER_ABORTED))
        await asyncio.wait_for(service.waitForTreeWork(parent),5)
        assert lifecycle==[('start','child',True),('end','child','completed')]*2
        observation=await ctx.get('sessionQuery').observeSession('child',{})
        try:
            assert sum(event['type']=='subagent/descriptor' for event in observation.events)==1
            inherited=[event['seq'] for event in observation.events
                       if event['type']=='session/end-seed' and event['data'].get('inherited')]
            assert inherited==([2] if backend=='fork' else [])
        finally:observation.dispose()
        await provider_owner.dispose()
        assert service.getProvider(backend) is None
        await owner.dispose()
        assert ctx.get('subagents') is None
    finally:await ctx.fiber.dispose()
