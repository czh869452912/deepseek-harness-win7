from types import SimpleNamespace
import pytest
from dsh.core.abort import AbortController
from dsh.core.scope import scope_of
from dsh.subagent.runtime import SubagentPlugin
from dsh.subagent.in_process import SpawnInProcess
from dsh.subagent.canonical_tools import CanonicalToolSubagent
from test_subagent_in_process import setup
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin


@pytest.mark.parametrize('reason,headline', [
    ('completed', None), ('aborted', 'subagent run was cancelled'),
    ('error', 'subagent run failed'), ('max-tokens', 'subagent run hit its token limit before finishing'),
    ('refusal', 'subagent declined the task'), ('custom', 'subagent run ended abnormally (custom)')])
@pytest.mark.parametrize('diagnostic', [None, '', 'provider detail'])
@pytest.mark.parametrize('partial', ['', 'preserved answer'])
@pytest.mark.asyncio
async def test_foreground_retains_stop_reason_diagnostic_partial_and_disposal(reason, headline, diagnostic, partial):
    import asyncio
    from dsh.subagent.canonical_tools import foreground
    value = dict(stopReason=reason, output=[dict(type='text', text=partial), dict(type='image', data='excluded')])
    if diagnostic is not None:
        value['diagnostic'] = diagnostic
    future = asyncio.get_running_loop().create_future()
    future.set_result(value)
    disposed = []
    async def dispose():
        disposed.append('disposed')
    run = SimpleNamespace(id='actual-result', result=future, dispose=dispose)
    if headline is None:
        assert await foreground(run) == dict(kind='foreground', runId='actual-result', output=value['output'])
    else:
        expected = headline
        if diagnostic is not None:
            expected += '\nDiagnostic: ' + diagnostic
        if partial:
            expected += '\nPartial output before the run ended:\n' + partial
        with pytest.raises(RuntimeError) as error:
            await foreground(run)
        assert str(error.value) == expected
    assert disposed == ['disposed']


@pytest.mark.asyncio
async def test_official_tool_executes_child_and_provider_unload_removes_tool():
    ctx, model, parent = await setup()
    await ctx.plugin(SubagentPlugin)
    tool_fiber = await ctx.plugin(CanonicalToolSubagent, {'provider': 'spawn', 'enableRunInBackground': False})
    assert ctx.get('tools').get('subagent', scope_of(parent.agent.ctx)) is None
    provider = await ctx.plugin(SpawnInProcess)
    try:
        tool = ctx.get('tools').get('subagent', scope_of(parent.agent.ctx))
        value = await tool.execute({'description': 'test child', 'prompt': 'actual task'},
            SimpleNamespace(agent=parent.agent, signal=AbortController().signal))
        assert value['kind'] == 'foreground' and value['output'][0]['text'] == 'actual child answer'
        assert ctx.get('agents').get(value['runId']) is None
        assert len(model.requests) == 1
        with pytest.raises(ValueError, match='disabled'):
            await tool.execute({'description': 'denied', 'prompt': 'task', 'run_in_background': True},
                SimpleNamespace(agent=parent.agent, signal=AbortController().signal))
        await provider.dispose()
        assert ctx.get('tools').get('subagent', scope_of(parent.agent.ctx)) is None
    finally:
        await tool_fiber.dispose()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_continuable_tool_returns_before_model_settlement(tmp_path):
    from test_subagent_continuation import BlockingModel
    ctx, _, parent = await setup()
    model = BlockingModel()
    ctx.set_service('llm', model)
    await ctx.plugin(JsonlSessionPersistencePlugin, {'root': str(tmp_path)})
    await ctx.plugin(SubagentPlugin)
    await ctx.plugin(SpawnInProcess)
    await ctx.plugin(CanonicalToolSubagent, {'provider': 'spawn', 'backgroundMode': 'continuable'})
    try:
        tool = ctx.get('tools').get('subagent', scope_of(parent.agent.ctx))
        result = await tool.execute({'description': 'background', 'prompt': 'actual task'},
            SimpleNamespace(agent=parent.agent, signal=AbortController().signal))
        assert result['kind'] == 'continuable'
        assert ctx.get('agents').get(result['subagentId']) is not None
        model.release.set()
        await ctx.get('subagents').continuations.drain()
    finally:
        model.release.set()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_child_report_is_scoped_and_live_revocable(tmp_path):
    from dsh.subagent.control_tools import ToolSubagentReport, ToolSubagentControl
    from test_subagent_continuation import BlockingModel
    ctx, _, parent = await setup()
    model = BlockingModel()
    ctx.set_service('llm', model)
    await ctx.plugin(JsonlSessionPersistencePlugin, {'root': str(tmp_path)})
    await ctx.plugin(SubagentPlugin)
    await ctx.plugin(SpawnInProcess)
    await ctx.plugin(ToolSubagentControl)
    reports = await ctx.plugin(ToolSubagentReport, {'reportDelivery': 'quiet'})
    try:
        service = ctx.get('subagents')
        started = await service.startContinuable(dict(provider='spawn', label='worker', request=dict(parent=parent.agent, prompt=[dict(type='text', text='work')])))
        child = ctx.get('agents').get(started['childId'])
        assert ctx.get('tools').get('report', scope_of(parent.agent.ctx)) is None
        tool = ctx.get('tools').get('report', scope_of(child.ctx))
        receipt = await tool.execute({'output': 'useful partial result'}, SimpleNamespace(agent=child, signal=AbortController().signal))
        assert receipt['messageId'] and parent.agent.status == 'idle'
        send = ctx.get('tools').get('send_message', scope_of(parent.agent.ctx))
        queued = await send.execute({'subagent_id': child.id, 'message': 'more work'}, SimpleNamespace(agent=parent.agent, signal=AbortController().signal))
        assert queued['messageId']
        await reports.dispose()
        assert ctx.get('tools').get('report', scope_of(child.ctx)) is None
        model.release.set()
        await service.continuations.drain()
    finally:
        model.release.set()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_agent_scoped_model_selection_samples_setting_once():
    from dsh.subagent.model_selection import ModelSelectionSettings, read_policy
    from dsh.llm.llm_service import LlmRuntime
    from dsh.llm.llm_deepseek import LLMDeepSeekPlugin
    ctx, _, parent = await setup()
    await ctx.plugin(SubagentPlugin)
    await ctx.plugin(SpawnInProcess)
    await ctx.plugin(ModelSelectionSettings, dict(enabled=True, allowedModels=[dict(provider='deepseek-official', model='deepseek-v4-flash')]))
    try:
        await parent.agent.ctx.plugin(CanonicalToolSubagent, dict(provider='spawn', modelSelectionSettings=True))
        tool = ctx.get('tools').get('subagent', scope_of(parent.agent.ctx))
        assert 'model' in tool.parameters['properties']
        assert read_policy(parent.agent.session) == [dict(provider='deepseek-official', model='deepseek-v4-flash')]
        assert ctx.get('tools').get('list_subagent_models', scope_of(parent.agent.ctx)) is not None
        with pytest.raises(ValueError, match='not allowed'):
            await tool.execute(dict(description='denied', prompt='task', provider='other', model='bad'),
                               SimpleNamespace(agent=parent.agent, signal=AbortController().signal))
        assert ctx.get('agents').list() == [parent.agent]
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_background_one_shot_is_admitted_by_jobs_before_child_start():
    from dsh.jobs.local import LocalJobRegistry
    ctx, model, parent = await setup()
    await ctx.plugin(SubagentPlugin)
    await ctx.plugin(SpawnInProcess)
    await ctx.plugin(LocalJobRegistry)
    await ctx.plugin(CanonicalToolSubagent, {'provider': 'spawn'})
    try:
        tool = ctx.get('tools').get('subagent', scope_of(parent.agent.ctx))
        args = dict(description='job child', prompt='real work', run_in_background=True)
        execution = SimpleNamespace(agent=parent.agent, signal=AbortController().signal)
        with pytest.raises(ValueError, match='controller'):
            await tool.execute(args, execution)
        assert not model.requests and ctx.get('agents').list() == [parent.agent]
        jobs = ctx.get('jobs')
        jobs.attach_controller('test')
        result = await tool.execute(args, execution)
        assert result['kind'] == 'background'
        completed = await jobs.wait(result['jobId'], 3000, parent.agent)
        assert completed['status'] == 'completed'
        assert ctx.get('agents').list() == [parent.agent]
        assert len(model.requests) == 1
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
async def test_setup_owns_delegation_tools_before_agent_publication(enabled):
    from dsh.subagent.model_selection import ModelSelectionSettings, read_policy
    ctx, model, parent = await setup()
    created = None
    await ctx.plugin(SubagentPlugin)
    await ctx.plugin(SpawnInProcess)
    routes = [dict(provider='alpha', model='fast')]
    await ctx.plugin(ModelSelectionSettings, dict(enabled=enabled, allowedModels=routes))
    identity = 'setup-delegation-' + str(enabled)

    async def configure(agent_ctx):
        assert ctx.get('agents').get(identity) is None
        await agent_ctx.plugin(CanonicalToolSubagent, dict(provider='spawn',
            modelSelectionSettings=True, enableRunInBackground=False))
        schemas = agent_ctx.get('tools').schemas(scope_of(agent_ctx))
        assert [item['name'] for item in schemas] == (['list_subagent_models', 'subagent'] if enabled else ['subagent'])

    try:
        created = await ctx.get('agents').create(dict(sessionId=identity, setup=configure))
        tool = ctx.get('tools').get('subagent', scope_of(created.agent.ctx))
        assert tool is not None
        assert ('provider' in tool.parameters['properties']) is enabled
        assert read_policy(created.agent.session) == (routes if enabled else None)
        result = await tool.execute(dict(description='setup child', prompt='actual task'),
            SimpleNamespace(agent=created.agent, signal=AbortController().signal))
        assert result['kind'] == 'foreground'
        assert result['output'][0]['text'] == 'actual child answer'
        assert ctx.get('agents').get(result['runId']) is None
        assert len(model.requests) == 1
        await created.dispose()
        assert ctx.get('tools').get('subagent', scope_of(created.agent.ctx)) is None
    finally:
        if created is not None:
            await created.dispose()
        await parent.dispose()
        await ctx.fiber.dispose()
