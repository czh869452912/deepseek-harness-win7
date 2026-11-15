import asyncio

import pytest

from dsh.context.agent_instructions.runtime_authorized import AuthorizedInstructionRuntime
from dsh.llm.message import create_user_message


@pytest.mark.asyncio
async def test_actual_plugin_tool_ancestry_step_boundary_inbox_order_and_unload(tmp_path):
    from scripts.rc022_instruction_runtime_probe import observe
    rows={row['name']:row for row in await observe(tmp_path)}
    assert rows['pending-identity']['same']
    assert len(rows['rejected-first']['pending']) == 1
    entered=rows['entered-order']['decision']['messages']
    assert [message['source']['kind'] for message in entered] == ['user','agent-instructions','user']
    assert rows['entered-order']['pending'] == []
    assert rows['already-visible']['decision']['messages'][0]['content'][0]['text'] == 'driver'
    assert rows['open-step-defers']['pending'] == []
    changed=rows['closed-step-projects']['pending'][0]
    assert changed['source']['changes'][0]['action'] == 'replace'
    assert rows['parent-boundary'] == dict(name='parent-boundary',inside=[0],outerError=True)
    assert 'successful child of failed outer' in rows['outer-completion-projects-child']['pending'][0]['content'][0]['text']
    assert rows['failed-tool-no-projection']['pending'] == []
    replacement=rows['directory-replacement']['pending'][0]
    assert replacement['source']['baseline'] is True
    assert 'replaces all earlier workspace instruction baselines' in replacement['content'][0]['text']
    concurrent=rows['serialized-concurrent-projections']['pending']
    assert len(concurrent) == 1
    assert {change['path'] for change in concurrent[0]['source']['changes']} == {'pkg\\alpha\\AGENTS.md','pkg\\beta\\AGENTS.md'}
    assert rows['unloaded-no-projection']['inboxEvents'] == 0


@pytest.mark.asyncio
async def test_actual_driver_persists_baseline_before_model_and_avoids_second_baseline(tmp_path,monkeypatch):
    from scripts.rc022_subagent_fixture import setup
    from scripts.oracles.generate_agent_machine_current_cases import response
    from dsh.context.agent_instructions.runtime_authorized import AuthorizedAgentInstructionsPlugin
    project=tmp_path/'project';project.mkdir();(project/'.git').write_text('marker',encoding='utf-8');(project/'AGENTS.md').write_text('driver baseline',encoding='utf-8')
    monkeypatch.setenv('DSH_HOME',str(tmp_path/'home'));monkeypatch.setenv('DSH_AGENTS_HOME',str(tmp_path/'shared'))
    fixture=await setup(tmp_path/'sessions',script=[response(),response()],directory=project);ctx=fixture.ctx;handle=None;observed=[]
    try:
        await ctx.plugin(AuthorizedAgentInstructionsPlugin,dict(maxBytes=65536))
        def request(payload,next_fn):
            observed.append([event['data']['source']['kind'] for event in handle.agent.session.snapshotEvents()
                if event['type']=='user/message' and event['data']['source']['kind'] != 'runtime-context'])
            return next_fn()
        ctx.on('llm/stream',request)
        handle=await ctx.agents.create(dict(sessionId='driver',meta=dict(cwd=str(project)),agentOptions=dict(provider='script',model='model')))
        for text in ('first','second'):
            handle.agent.followup(create_user_message(dict(content=[dict(type='text',text=text)],source=dict(kind='user'))))
            await handle.agent.whenIdle()
        baselines=[event for event in handle.agent.session.snapshotEvents() if event['type']=='user/message' and event['data']['source'].get('baseline') is True]
        assert len(baselines) == 1 and 'driver baseline' in baselines[0]['data']['content'][0]['text']
        assert observed == [['user','agent-instructions'],['user','agent-instructions','user']]
    finally:
        if handle is not None:await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_lifecycle_abort_during_provider_read_prevents_inbox_commit(tmp_path,monkeypatch):
    from scripts.rc022_subagent_fixture import setup
    project=tmp_path/'project';project.mkdir();(project/'.git').write_text('marker',encoding='utf-8');(project/'AGENTS.md').write_text('held baseline',encoding='utf-8')
    monkeypatch.setenv('DSH_HOME',str(tmp_path/'home'));monkeypatch.setenv('DSH_AGENTS_HOME',str(tmp_path/'shared'))
    fixture=await setup(tmp_path/'sessions',directory=project);ctx=fixture.ctx;handle=None;task=None;entered=asyncio.Event();release=asyncio.Event()
    try:
        runtime=AuthorizedInstructionRuntime(ctx,dict(maxBytes=65536));original=ctx.fs.streamText
        async def held(target,signal):entered.set();await release.wait();return await original(target,signal)
        ctx.fs.streamText=held
        handle=await ctx.agents.create(dict(sessionId='held',meta=dict(cwd=str(project)),agentOptions=dict(provider='script',model='model')))
        task=asyncio.ensure_future(runtime.compose_and_sync(handle.agent,runtime.lifecycle.signal,[]))
        await asyncio.wait_for(entered.wait(),2);runtime.dispose();release.set()
        with pytest.raises(RuntimeError,match='agent-instructions disposed'):await task
        assert handle.agent.inbox.nextStep == [] and handle.agent.session not in runtime.preparations
    finally:
        release.set()
        if task is not None:await asyncio.gather(task,return_exceptions=True)
        if handle is not None:await handle.dispose()
        await ctx.fiber.dispose()
