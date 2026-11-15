import pytest
from scripts.rc022_tool_recovery_probe import observe


@pytest.mark.asyncio
async def test_live_and_tail_tool_recovery():
    rows=await observe()
    for row in rows[:16]:
        assert row['repeat']
        for event in row['results']:
            assert event['data']['message']['role']=='tool'
            assert event['data']['message']['id'].startswith(row['test']['cause']+'-tool-result-')
    by={row['action']:row for row in rows[16:]}
    assert [item['code'] for item in by['executor-unloaded']['results']]==['TOOL_NOT_STARTED']*2
    assert [item['code'] for item in by['write-failure']['results']]==['TOOL_OUTCOME_UNKNOWN','TOOL_NOT_STARTED']
    assert by['write-failure']['bodies']==['c0']
    assert by['write-failure']['failures']==[dict(primary=True,aggregate=[],cause=False)]
    assert by['recovery-failure']['results']==[]
    assert by['recovery-failure']['failures']==[dict(primary=False,aggregate=[True,True],cause=True)]
    assert all(row['tail']==['step/end','turn/end'] for row in by.values())


@pytest.mark.asyncio
@pytest.mark.parametrize('compression',['none','zstd'])
async def test_v4_cold_read_and_resume_repair_actual_storage(tmp_path,compression):
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore,CurrentSession
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin
    from dsh.session.cold_read import readColdSessionLog
    from dsh.llm.message import create_assistant_message
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    ctx=Context();handle=None
    try:
        for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
        await ctx.plugin(CurrentJsonlSessionPersistencePlugin,dict(root=str(tmp_path/'sessions'),compression=compression))
        await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
        seed=CurrentSession.create('saved',format_version=4)
        seed.append('turn/start',dict(turn=1));seed.append('step/start',dict(turn=1,step=1))
        seed.append('assistant/message',dict(turn=1,step=1,stream=[],message=create_assistant_message(dict(
            source=dict(provider='script',model='model'),content=[dict(type='tool-call',id=key,name='work',arguments='{}') for key in ('a','b')]))),'append')
        seed.append('tool/call',dict(turn=1,step=1,callId='a',name='work',arguments='{}'))
        backend=ctx.sessionPersistence;writer=await backend.create(seed.header)
        try:await writer.append(seed.events)
        finally:await writer.close()
        cold=await readColdSessionLog(backend,'saved')
        handle=await ctx.agents.resume(dict(resumeSessionId='saved',agentOptions=dict(provider='script',model='model')))
        for events in (cold['events'],handle.agent.session.events):
            results=[event for event in events if event['type']=='tool/result']
            assert [event['data']['error']['code'] for event in results]==['TOOL_OUTCOME_UNKNOWN','TOOL_NOT_STARTED']
            assert all(event['data']['message']['role']=='tool' for event in results)
    finally:
        if handle is not None:await handle.dispose()
        await ctx.fiber.dispose()
