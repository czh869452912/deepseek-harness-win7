"""Shared error graph contracts and actual diagnostic consumers."""
import asyncio
import json
from pathlib import Path

import pytest

from dsh.cordis.context import Context
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.llm.error import AggregateError, HarnessError, error_chain
from dsh.llm.llm_service import LlmError
from scripts.oracles.compaction_python import transaction
from scripts.oracles.error_chain_fixtures import build

ROOT = Path(__file__).resolve().parents[1]
GRAPHS = json.loads((ROOT / 'scripts/oracles/error-chain-cases.json').read_text(encoding='utf-8'))
TRANSACTIONS = json.loads((ROOT / 'scripts/oracles/error-transaction-cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', GRAPHS, ids=[case['mode'] for case in GRAPHS])
def test_diagnostic_graph(case):
    assert error_chain(build(case)) == case['expected']


@pytest.mark.asyncio
@pytest.mark.parametrize('case', TRANSACTIONS, ids=[case['mode'] for case in TRANSACTIONS])
async def test_actual_transaction_keeps_error_identity_closes_once_and_flushes(case):
    observed = await transaction(case)
    assert observed['outcome']['sameFailure'] is True
    assert observed['endAttempts'] == 1
    assert observed['generation'] == 0 and observed['nodes'] == [0, 1]
    assert observed['summaries'] == []
    if case.get('closeFailure'):
        assert observed['outcome']['code'] == ('commit' if case['manual'] else None)
        assert observed['failedEnds'] == [] and observed['flushes'] == 0
        assert [event['type'] for event in observed['events']] == ['compaction/start']
    else:
        expected_code = 'summary' if case['manual'] else case['nodes'][case['root']].get('code')
        assert observed['outcome']['code'] == expected_code
        assert observed['failedEnds'] == [dict(error=case['expected'], turn=None if case['manual'] else 1,
            sourceCommandId='real-command', sameIdentity=True)]
        assert observed['flushes'] == 1
        assert [event['type'] for event in observed['events']] == ['compaction/start', 'compaction/end']


def test_native_explicit_cause_and_implicit_context_boundary():
    underlying = OSError('socket closed')
    try:
        raise RuntimeError('request failed') from underlying
    except RuntimeError as wrapped:
        assert error_chain(wrapped) == 'request failed: socket closed'
        wrapped.cause = None
        assert error_chain(wrapped) == 'request failed'
    try:
        try:
            raise underlying
        except OSError:
            raise RuntimeError('handled replacement')
    except RuntimeError as wrapped:
        assert error_chain(wrapped) == 'handled replacement'


@pytest.mark.parametrize('field', ['message', 'name', 'cause', 'errors'])
def test_attribute_error_in_a_real_getter_is_not_treated_as_absence(field):
    def hostile(self):
        raise AttributeError('getter failed')
    base = AggregateError if field == 'errors' else RuntimeError
    cls = type('Hostile', (base,), {field: property(hostile)})
    # Avoid the normal constructor writes to deliberately hostile descriptors.
    value = cls.__new__(cls)
    RuntimeError.__init__(value, '' if field == 'name' else 'visible') if field != 'errors' else Exception.__init__(value, 'agg')
    if field == 'errors':
        value.message = 'agg'
    assert error_chain(value) == '<unrenderable value>'


def test_native_harness_and_llm_message_keeps_code_out_of_diagnostic_text():
    root = OSError('connection refused')
    assert error_chain(HarnessError('request failed', 'TRANSPORT', {'cause': root})) == 'request failed: connection refused'
    assert error_chain(HarnessError('request failed', cause=root)) == 'request failed: connection refused'
    failure = LlmError('provider failed', 'SERVER', status=503, providerRetryAfterMs=50, requestId='request')
    failure.__cause__ = root
    assert error_chain(failure) == 'provider failed: connection refused'
    assert failure.failure == dict(message='provider failed', code='SERVER', status=503,
        providerRetryAfterMs=50, requestId='request')


def test_error_getter_reads_follow_source_conditionals():
    calls = []
    class Changing(RuntimeError):
        @property
        def message(self):
            calls.append('message')
            return 'first' if calls.count('message') == 1 else 'second'
        @property
        def cause(self):
            calls.append('cause')
            return RuntimeError('last' if calls.count('cause') == 3 else 'unused')
    assert error_chain(Changing()) == 'second: last'
    assert calls == ['message', 'message', 'cause', 'cause', 'cause']


@pytest.mark.parametrize('owner', ['events', 'loader', 'group'])
def test_framework_aggregates_share_identity_and_do_not_coerce_members_during_construction(owner):
    from dsh.cordis.events import AggregateError as EventAggregate
    from dsh.cordis.loader import AggregateError as LoaderAggregate
    from dsh.cordis.loader_group import LoaderAggregateError
    chain = RuntimeError('outer')
    chain.__cause__ = OSError('inner')
    class Hostile(RuntimeError):
        def __str__(self):
            raise ValueError('coercion failed')
    members = [chain, Hostile()]
    value = (EventAggregate(members) if owner == 'events' else
        LoaderAggregate(members, 'failed') if owner == 'loader' else LoaderAggregateError(members, 'failed'))
    assert isinstance(value, AggregateError)
    assert error_chain(value) == ('AggregateError' if owner == 'events' else 'failed') + ' [outer: inner; <unrenderable value>]'
    assert '<unrenderable value>' in str(value)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['chained', 'hostile', 'llm'])
async def test_real_agent_loop_durable_failure(kind):
    root = OSError('socket closed')
    failure = RuntimeError('request failed')
    failure.__cause__ = root
    if kind == 'hostile':
        class Hostile(RuntimeError):
            def __str__(self):
                raise RuntimeError('coercion failed')
        failure = Hostile()
    elif kind == 'llm':
        failure = LlmError('provider failed', 'SERVER', status=503, providerRetryAfterMs=50, requestId='r1')
        failure.__cause__ = root
    class Model:
        provider, model = 'fixture', 'fixture'
        async def chat_completion_stream(self, request):
            raise failure
            yield None
    ctx = Context()
    ctx.set_service('llm', Model())
    for plugin in (SessionPlugin, ToolsPlugin, SystemPrompt, AgentLoopPlugin):
        await ctx.plugin(plugin)
    handle = await ctx.get('agent_loop').create('error-' + kind)
    try:
        handle.agent.followup('question')
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        events = handle.agent.session.events
        assert events[-1]['type'] == 'turn/end'
        expected = (failure.failure if kind == 'llm' else dict(code='UNKNOWN',
            message='<unrenderable value>' if kind == 'hostile' else 'request failed: socket closed'))
        assert events[-1]['data']['reason'] == dict(kind='error', error=expected)
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_canonical_web_errors_and_failed_compaction_survive_restart(tmp_path):
    from canonical_web_fixture import web_context, close_web_context
    from dsh.compaction.invariant import CompactionInvariantPlugin
    from dsh.diagnostics.invariants import InvariantRegistry
    underlying = OSError('socket closed')
    failure = LlmError('provider failed', 'SERVER')
    failure.__cause__ = underlying
    class Adapter:
        async def prepare_call(self, provider, model, signal=None):
            return dict(model=dict(provider=provider, id=model, name=model), stream=self.stream)
        async def stream(self, request):
            raise failure
            yield None
    home, identity = tmp_path / 'home', 'failed-compact'
    ctx = await web_context(home)
    try:
        await ctx.plugin(InvariantRegistry)
        await ctx.plugin(CompactionInvariantPlugin)
        await ctx.get('sessionController').create(dict(sessionId=identity, cwd=str(tmp_path), agentPreset='standard'))
        agent = ctx.get('agents').get(identity)
        emitted = []
        ctx.on('api-session/error', lambda *args: emitted.append(args))
        ctx.emit('agent/error', dict(agent=agent, error=failure))
        assert emitted == [(identity, 'provider failed: socket closed')]
        ctx.get('llm').register_adapter(['failure-probe'], Adapter())
        agent.session.append_request_header(dict(config=dict(provider='failure-probe', model='probe')))
        agent.session.append_user_message('important facts ' * 300)
        agent.session.append_user_message('recent question')
        result = await ctx.get('commands').execute(agent, '/compact', [], None)
        assert result.result['kind'] == 'error'
        await agent.session.flush()
        expected = [event for event in agent.session.events if event['type'].startswith('compaction/')]
        assert [event['type'] for event in expected] == ['compaction/start', 'compaction/end']
        assert expected[-1]['data']['error'] == 'provider failed'
        assert agent.session.surface.replace_generation == 0
    finally:
        await ctx.get('sessionProjectionCache').close()
        await close_web_context(ctx)
    ctx = await web_context(home)
    try:
        restored = await ctx.get('sessionController').inspect(identity)
        assert [event for event in restored['events'] if event['type'].startswith('compaction/')] == expected
    finally:
        await ctx.get('sessionProjectionCache').close()
        await close_web_context(ctx)
