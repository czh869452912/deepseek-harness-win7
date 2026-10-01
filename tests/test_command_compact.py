import asyncio
from types import SimpleNamespace

import pytest

from dsh.compaction.command_compact import CommandCompactPlugin
from dsh.compaction.engine import CompactionEngine, ManualCompactionError
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.agent import Agent, AgentOptions
from dsh.core.session import Session
from dsh.interaction.commands import CommandsPlugin
from dsh.llm.token_meter import TokenMeter
from dsh.core.scope import create_scope, ScopeKey, scope_of


class Backend:
    def __init__(self, result=True, failure=None, operation=None):
        self.result, self.failure, self.operation = result, failure, operation
        self.calls = []

    async def compact_now(self, agent, signal, command_id):
        self.calls.append((agent, signal, command_id))
        if self.operation:
            return await self.operation(agent, signal, command_id)
        if self.failure:
            raise self.failure
        if self.result is None:
            return None
        identity = dict(compactionId='test-compaction', sourceCommandId=command_id)
        agent.session.append('compaction/start', dict(identity, turn=None))
        summary = agent.session.append('compaction/summary', dict(identity,
            summary=[dict(type='text', text='summary')], shadowedRange=dict(start=1, end=7),
            shadowedSeqs=[1, 3, 7], shadowedTokenCount=42, provider='test', model='model'))
        agent.session.append('compaction/end', dict(identity, turn=None))
        return dict(identity, shadowedSeqs=[1, 3, 7], shadowedTokenCount=42, summarySeq=summary['seq'])


async def harness(backend):
    ctx = Context()
    await ctx.plugin(CommandsPlugin)
    ctx.set_service('compaction', backend)
    plugin = await ctx.plugin(CommandCompactPlugin)
    agent = Agent(Session('command-compact', ctx=ctx), ctx=ctx)
    return ctx, plugin, agent


def lifecycle(agent, args, result):
    events = [event for event in agent.session.events if event['type'].startswith('command/')]
    run, done = events[-2:]
    assert run['data'] == dict(commandId=run['data']['commandId'], name='compact', args=args, source=dict(kind='user'))
    assert done['data'] == dict(commandId=run['data']['commandId'], **result)
    assert run['type'] == 'command/run' and done['type'] == 'command/done'
    assert not agent.session.surface.nodes and not agent.session.derive_messages()
    return run['data']['commandId']


@pytest.mark.asyncio
async def test_command_result_and_exact_agent_signal_identity_provenance():
    backend = Backend()
    ctx, plugin, agent = await harness(backend)
    signal = AbortController().signal
    try:
        assert ctx.commands.find(agent, 'compact').description == 'Compact older conversation history'
        execution = await ctx.commands.execute(agent, '/compact', [], signal)
        expected = dict(kind='success', text='Compacted 3 history items (~42 tokens).', sourceEventSeq=2)
        assert execution.result == expected
        assert backend.calls == [(agent, signal, execution.command_id)]
        assert lifecycle(agent, '', expected) == execution.command_id
        summary = agent.session.events[execution.result['sourceEventSeq']]
        assert summary['data']['sourceCommandId'] == execution.command_id
        await plugin.dispose()
        assert ctx.commands.find(agent, 'compact') is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_required_compaction_injection_does_not_publish_missing_capability_command():
    ctx = Context()
    await ctx.plugin(CommandsPlugin)
    plugin = await ctx.plugin(CommandCompactPlugin)
    agent = Agent(Session('missing'), ctx=ctx)
    assert CommandCompactPlugin.inject == ['commands', 'compaction']
    assert ctx.commands.find(agent, 'compact') is None
    await plugin.dispose()
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_command_scope_uses_bound_agent_key_and_preserves_preset_isolation():
    ctx = Context()
    await ctx.plugin(CommandsPlugin)
    parent = create_scope(ctx, ScopeKey('preset'))
    first = create_scope(ctx, ScopeKey('configured-agent'), dict(parent=scope_of(parent.ctx)))
    other = create_scope(ctx, ScopeKey('other-agent'))
    owner = Agent(Session('owner'), ctx=first.ctx)
    outsider = Agent(Session('outsider'), ctx=other.ctx)
    parent.ctx.get('commands').register(dict(name='local', description='Preset-local command',
        handler=lambda invocation: dict(kind='success', text='local result')))
    try:
        assert ctx.get('commands').find(owner, 'local') is not None
        assert ctx.get('commands').find(outsider, 'local') is None
        execution = await ctx.get('commands').execute(owner, '/local', [], AbortController().signal)
        assert execution.result == dict(kind='success', text='local result')
        await parent.dispose()
        assert ctx.get('commands').find(owner, 'local') is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('suffix, valid', [('', True), (' \ufeff\u2028', True), (' now', False), (' \u0085', False)])
async def test_argument_validation_uses_js_whitespace_and_null_history(suffix, valid):
    backend = Backend(result=None)
    ctx, _, agent = await harness(backend)
    try:
        execution = await ctx.commands.execute(agent, '/compact' + suffix, [], AbortController().signal)
        expected = dict(kind='success', text='No compactable history yet.') if valid else dict(kind='error', text='Usage: /compact (no arguments)')
        assert execution.result == expected
        assert len(backend.calls) == int(valid)
        lifecycle(agent, suffix, expected)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('code, text', [
    ('busy', 'Compaction is unavailable because this process has an active compaction, or the agent is not idle.'),
    ('cancelled', 'Compaction cancelled.'),
    ('changed', 'The history selected for compaction changed before it could be replaced. The conversation is unchanged; the attempt is recorded in the session log.'),
    ('summary', 'Compaction could not produce a useful summary. The conversation is unchanged; the attempt is recorded in the session log.'),
    ('commit', 'Compaction did not finish cleanly; some session history may have changed. Inspect the current session state before retrying.'),
    ('persistence', 'Compaction finished, but the session could not be saved.'),
])
async def test_expected_errors_have_original_direct_presentation(code, text):
    ctx, _, agent = await harness(Backend(failure=ManualCompactionError(code, 'private backend detail')))
    try:
        execution = await ctx.commands.execute(agent, '/compact', [], AbortController().signal)
        assert execution.result == dict(kind='error', text=text)
        lifecycle(agent, '', dict(kind='error', text=text))
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unknown_backend_error_propagates_with_command_lifecycle():
    failure = RuntimeError('unexpected backend bug')
    ctx, _, agent = await harness(Backend(failure=failure))
    try:
        with pytest.raises(RuntimeError) as error:
            await ctx.commands.execute(agent, '/compact', [], AbortController().signal)
        assert error.value is failure
        lifecycle(agent, '', dict(kind='error', text=str(failure)))
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_caller_abort_in_backend_wins_same_turn_handler_return():
    control = AbortController()
    reason = RuntimeError('operator cancelled')
    async def operation(agent, signal, command_id):
        control.abort(reason)
        raise ManualCompactionError('summary', 'late failure')
    ctx, _, agent = await harness(Backend(operation=operation))
    try:
        with pytest.raises(RuntimeError) as error:
            await ctx.commands.execute(agent, '/compact', [], control.signal)
        assert error.value is reason
        lifecycle(agent, '', dict(kind='error', text=str(reason)))
        assert not control.signal._listeners
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unload_unregisters_then_drains_aborted_close_and_flush():
    entered, close, closed, flush, flushed = [asyncio.Event() for _ in range(5)]
    reason = RuntimeError('operator cancelled')
    async def operation(agent, signal, command_id):
        entered.set()
        await close.wait()
        closed.set()
        await flush.wait()
        flushed.set()
        raise reason
    ctx, plugin, agent = await harness(Backend(operation=operation))
    control = AbortController()
    pending = asyncio.create_task(ctx.commands.execute(agent, '/compact', [], control.signal))
    await entered.wait()
    control.abort(reason)
    with pytest.raises(RuntimeError) as error:
        await pending
    assert error.value is reason
    lifecycle(agent, '', dict(kind='error', text=str(reason)))
    disposal = asyncio.ensure_future(plugin.dispose())
    try:
        for _ in range(50):
            if ctx.commands.find(agent, 'compact') is None:
                break
            await asyncio.sleep(0)
        assert ctx.commands.find(agent, 'compact') is None and not disposal.done()
        assert await ctx.commands.execute(agent, '/compact', [], AbortController().signal) is None
        close.set()
        await closed.wait()
        assert not disposal.done()
        flush.set()
        await asyncio.wait_for(disposal, 2)
        assert flushed.is_set()
    finally:
        close.set()
        flush.set()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_backend_maintenance_overlap_is_expected_busy_and_first_call_completes():
    ctx = Context()
    await ctx.plugin(CommandsPlugin)
    entered, release = asyncio.Event(), asyncio.Event()
    async def stream(request):
        entered.set()
        await release.wait()
        yield dict(type='text-delta', index=0, text='checkpoint')
        yield dict(type='finish', reason=dict(kind='stop'))
    ctx.set_service('llm', SimpleNamespace(stream=stream))
    TokenMeter(ctx)
    CompactionEngine(ctx=ctx)
    await ctx.plugin(CommandCompactPlugin)
    session = Session('actual-command', ctx=ctx)
    session.append_user_message('important facts ' * 300)
    session.append_user_message('recent question')
    agent = Agent(session, AgentOptions(provider='test', model='model'), ctx=ctx)
    ctx.on('session/flush', lambda current: None)
    pending = asyncio.create_task(ctx.commands.execute(agent, '/compact', [], AbortController().signal))
    try:
        await entered.wait()
        second = await ctx.commands.execute(agent, '/compact', [], AbortController().signal)
        assert second.result['kind'] == 'error' and 'not idle' in second.result['text']
        assert len([event for event in session.events if event['type'] == 'compaction/start']) == 1
        release.set()
        first = await pending
        assert first.result['kind'] == 'success'
        assert session.events[first.result['sourceEventSeq']]['data']['sourceCommandId'] == first.command_id
        assert agent.status == 'idle'
    finally:
        release.set()
        await pending
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('preset', ['standard', 'ptc', 'cordis'])
async def test_canonical_web_command_compaction_and_cold_restart(tmp_path, preset):
    from canonical_web_fixture import web_context, close_web_context
    from dsh.presets.mount import service_for_agent
    from dsh.compaction.invariant import CompactionInvariantPlugin
    from dsh.diagnostics.invariants import InvariantRegistry
    requests = []
    class Adapter:
        async def prepare_call(self, provider, model, signal=None):
            return dict(model=dict(provider=provider, id=model, name=model), stream=self.stream)
        async def stream(self, request):
            requests.append(request)
            yield dict(type='text-delta', index=0, text='Keep the implementation facts.')
            yield dict(type='finish', reason=dict(kind='stop'))
    directory, identity = tmp_path / 'home', 'compact-' + preset
    ctx = await web_context(directory)
    try:
        await ctx.plugin(InvariantRegistry)
        await ctx.plugin(CompactionInvariantPlugin)
        await ctx.get('sessionController').create(dict(sessionId=identity, cwd=str(tmp_path), agentPreset=preset))
        agent = ctx.get('agents').get(identity)
        assert service_for_agent(ctx, agent, 'compaction') is not None
        assert ctx.get('commands').find(agent, 'compact') is not None
        ctx.get('llm').register_adapter(['compact-probe'], Adapter())
        agent.session.append_request_header(dict(config=dict(provider='compact-probe', model='probe'), system='original prefix'))
        agent.session.append_user_message('implementation facts ' * 300)
        agent.session.append_user_message('recent question')
        execution = await ctx.get('commands').execute(agent, '/compact', [], AbortController().signal)
        assert execution.result['kind'] == 'success', execution.result
        record = agent.session.events[execution.result['sourceEventSeq']]
        assert record['type'] == 'compaction/summary'
        assert record['data']['sourceCommandId'] == execution.command_id
        assert record['data']['llmStreamCall'] is True
        assert len(requests) == 1 and requests[0]['purpose'] == 'compaction'
        assert requests[0]['system'] == 'original prefix'
        assert agent.session.surface.replace_generation == 1
        await agent.session.flush()
        expected = [event for event in agent.session.events if event['type'].startswith(('command/', 'compaction/'))]
        assert [event['type'] for event in expected] == ['command/run', 'compaction/start', 'compaction/summary', 'compaction/end', 'command/done']
    finally:
        await ctx.get('sessionProjectionCache').close()
        await close_web_context(ctx)
    ctx = await web_context(directory)
    try:
        await ctx.plugin(InvariantRegistry)
        await ctx.plugin(CompactionInvariantPlugin)
        restored = await ctx.get('sessionController').inspect(identity)
        actual = [event for event in restored['events'] if event['type'].startswith(('command/', 'compaction/'))]
        assert actual == expected
    finally:
        await ctx.get('sessionProjectionCache').close()
        await close_web_context(ctx)
