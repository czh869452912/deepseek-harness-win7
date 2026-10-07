"""Maintenance is externally idle, but retains Agent lifetime ownership."""
from dsh.llm.llm_service import LlmRuntime
import asyncio
import json
from pathlib import Path

import pytest

from dsh.compaction.engine import CompactionEngine, ManualCompactionError
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.core.session import Session, SessionPlugin
from dsh.llm.token_meter import TokenMeter
from dsh.llm.error import error_chain
from dsh.cordis.errors import ThrownValueError
from scripts.oracles.maintenance_python import observe, compaction

CASES = json.loads((Path(__file__).resolve().parents[1] / 'scripts/oracles/maintenance-cases.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('spec', [spec for spec in CASES if spec.get('kind') != 'compaction'],
    ids=[spec['mode'] for spec in CASES if spec.get('kind') != 'compaction'])
async def test_actual_maintenance_and_driver_contract(spec):
    row = await observe(spec)
    assert row['reserved'] and row['busy'] and row['waitsMaintenance']
    assert row['status'] == 'idle'
    assert row['cancellation'] == dict(aborted=bool(spec.get('cancel')), firstReason=bool(spec.get('cancel')))
    assert row['outcome'] == (dict(sameFailure=True) if spec.get('error') else dict(value=42))
    expected_claims = (['after cancel'] if spec.get('afterWake') and spec['cancel'] != 'disposed'
        else ['queued'] if spec.get('wake') and not spec.get('remove') and (not spec.get('cancel') or spec.get('keep'))
        else [])
    assert row['claims'] == expected_claims
    assert row['waitsDriver'] == bool(expected_claims)
    assert row['turns'] == (['turn/start', 'turn/end'] if expected_claims else [])
    assert row['queued'] == int(bool(spec.get('inject') or spec.get('idleCancel') or spec.get('cancel') == 'disposed' and spec.get('afterWake')))


@pytest.mark.asyncio
@pytest.mark.parametrize('spec', [spec for spec in CASES if spec.get('kind') == 'compaction'],
    ids=[spec['mode'] for spec in CASES if spec.get('kind') == 'compaction'])
async def test_compaction_maintenance_shared_cancellation_and_lifetime(spec):
    row = await compaction(spec)
    assert row['before'] == dict(pending=True, retained=True, registered=True, aborted=True)
    assert row['retainedInJob'] and row['clean'] and row['released'] == ['released']
    assert row['flushes'] == 1 and row['generation'] == int(spec['stage'] == 'flush')
    caller = spec['action'] in ('caller-first', 'caller-value')
    rendered = spec.get('rendered', '[object Object]')
    assert row['outcome'] == dict(code=None if caller else 'cancelled', callerReason=caller,
        rendered=rendered if caller else 'manual compaction was cancelled: ' + rendered)
    assert row['failedEnds'] == ([] if spec['stage'] == 'flush' else [rendered])


def test_thrown_value_carrier_preserves_live_value_and_cycles():
    value = dict(message='original')
    carrier = ThrownValueError(value)
    assert carrier.reason is value and error_chain(carrier) == 'original'
    value['message'] = ''
    assert error_chain(carrier) == ''
    value['message'] = 'updated'
    assert error_chain(carrier) == 'updated'
    carrier.value = carrier
    assert error_chain(carrier) == '<circular cause>'


@pytest.mark.asyncio
async def test_cancelled_result_and_idle_observers_do_not_cancel_owned_maintenance():
    agent = Agent(Session('observer-cancel'))
    entered, release = asyncio.Event(), asyncio.Event()
    signal_values = []
    async def job(signal):
        signal_values.append(signal)
        entered.set()
        await release.wait()
        return 42
    observer = asyncio.create_task(agent.runMaintenance(job))
    await entered.wait()
    idle = asyncio.create_task(agent.whenIdle())
    await asyncio.sleep(0)
    observer.cancel()
    idle.cancel()
    await asyncio.gather(observer, idle, return_exceptions=True)
    joined = asyncio.create_task(agent.when_idle())
    await asyncio.sleep(0)
    assert not joined.done() and agent._phase_kind == 'maintenance'
    assert not signal_values[0].aborted
    release.set()
    await asyncio.wait_for(joined, 2)
    assert agent._phase_kind == 'idle' and not agent._idle_futures
    await agent.ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['sync-error', 'future'])
async def test_job_failure_identity_and_generic_awaitable_are_preserved(kind):
    agent = Agent(Session('job-result'))
    failure = RuntimeError('job failed')
    future = asyncio.get_running_loop().create_future()
    def job(signal):
        if kind == 'sync-error':
            raise failure
        return future
    result = agent.runMaintenance(job)
    assert agent._phase_kind == 'maintenance'
    with pytest.raises(RuntimeError, match='active work'):
        agent.runMaintenance(job)
    if kind == 'sync-error':
        with pytest.raises(RuntimeError) as error:
            await result
        assert error.value is failure
    else:
        idle = asyncio.create_task(agent.whenIdle())
        await asyncio.sleep(0)
        assert not idle.done()
        future.set_result(42)
        assert await result == 42
        await idle
    await agent.whenIdle()
    assert agent._phase_kind == 'idle'
    await agent.ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['summary', 'flush'])
async def test_factory_disposal_joins_real_compaction_before_releasing_scope(stage):
    ctx = Context()
    entered, release = asyncio.Event(), asyncio.Event()
    markers, observed_signals = [], []
    pending = disposal = None
    try:
        await ctx.plugin(SessionPlugin)
        await ctx.plugin(AgentPlugin)
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(ToolsPlugin)
        await ctx.plugin(LlmRuntime)
        await ctx.plugin(AgentLoopPlugin)
        TokenMeter(ctx)
        engine = CompactionEngine(ctx=ctx, config=dict(auto=False))
        handle = await ctx.get('agents').create(session_id='dispose-' + stage,
            options=AgentOptions(provider='probe', model='model'))
        agent = handle.agent
        agent.ctx.set_service('maintenanceMarker', object())
        agent.ctx.disposable(lambda: markers.append('released'))
        session = agent.session
        session.append_user_message('important facts ' * 300)
        session.append_user_message('recent question')
        async def summarize(input, owner, signal):
            observed_signals.append(signal)
            if stage == 'summary':
                entered.set()
                await release.wait()
                assert owner.ctx.get('maintenanceMarker') is not None and markers == []
            return dict(summary=[dict(type='text', text='checkpoint')], provider='probe', model='model')
        async def flush():
            if stage == 'flush':
                entered.set()
                await release.wait()
            assert agent.ctx.get('maintenanceMarker') is not None and markers == []
        engine.summarize = summarize
        session.flush = flush
        pending = asyncio.create_task(engine.compact_now(agent))
        await entered.wait()
        disposal = asyncio.create_task(handle.dispose())
        for _ in range(5):
            await asyncio.sleep(0)
        assert observed_signals[0].aborted and observed_signals[0].reason == dict(kind='disposed')
        assert not disposal.done() and markers == []
        assert ctx.get('agents').get(agent.id) is agent
        assert ctx.get('sessions').get(session.id) is session
        release.set()
        with pytest.raises(ManualCompactionError) as error:
            await pending
        assert error.value.code == 'cancelled'
        await asyncio.wait_for(disposal, 2)
        assert markers == ['released']
        assert ctx.get('agents').get(agent.id) is None and ctx.get('sessions').get(session.id) is None
        assert [e['type'] for e in session.events if e['type'].startswith('compaction/')] == (
            ['compaction/start', 'compaction/end'] if stage == 'summary'
            else ['compaction/start', 'compaction/summary', 'compaction/end'])
        assert session.surface.replace_generation == int(stage == 'flush')
    finally:
        release.set()
        await asyncio.gather(*(task for task in (pending, disposal) if task is not None), return_exceptions=True)
        await ctx.fiber.dispose()
