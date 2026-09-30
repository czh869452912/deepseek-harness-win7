import asyncio
import gc
import weakref
from types import SimpleNamespace

import pytest

from dsh.compaction.compaction_basic.config import (
    resolve_config, resolve_target_policy, resolve_compact_spec, TargetPressureConfigError,
)
from dsh.compaction.engine import CompactionEngine, CompactionBasicPlugin
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.session import SessionStore, SessionPlugin
from dsh.llm.token_meter import TokenMeter


@pytest.mark.parametrize('config', [
    {'thresholdTokens': 100}, {'models': {}}, {'keepRecentMessages': 2},
    {'thresholdRatio': 0}, {'thresholdRatio': 1.1}, {'thresholdRatio': True},
    {'thresholdRatio': float('nan')}, {'retainRatio': float('inf')},
    {'retainRatio': 0}, {'retainRatio': 0.8}, {'thresholdRatio': 0.1},
    {'retainTokens': -1}, {'retainTokens': True}, {'retainTokens': 1.1},
    {'retainRatio': 0.2, 'retainTokens': 100}, {'maxTokens': 0},
    {'compactionRetries': -1}, {'maxOverflowRetries': 1.1}, {'auto': 'yes'},
    {'summarizationProvider': 'p'}, {'summarizationModel': ''},
    {'summarizationProvider': 1, 'summarizationModel': 'm'},
    {'summarizationProvider': '', 'summarizationModel': 'm'},
    {'modelPolicies': {}}, {'modelPolicies': [None]}, {'modelPolicies': [[]]},
    {'modelPolicies': [{'provider': '', 'model': 'm'}]},
    {'modelPolicies': [{'provider': 'p', 'model': 1}]},
    {'modelPolicies': [{'provider': 'p', 'model': 'm', 'retainRatio': 0.9}]},
    {'modelPolicies': [{'provider': 'p', 'model': 'm', 'thresholdRatio': 0.1}]},
    {'modelPolicies': [{'provider': 'p', 'model': 'm', 'summarizationModel': ''}]},
    {'modelPolicies': [{'provider': 'p', 'model': 'm', 'thresholdRato': 0.5}]},
    {'modelPolicies': [{'provider': 'p', 'model': 'm'}, {'provider': 'p', 'model': 'm'}]},
])
def test_invalid_configuration_rejected_before_registration(config):
    with pytest.raises(ValueError):
        CompactionBasicPlugin(config)


def test_route_policy_defaults_inheritance_clear_and_frozen_snapshots():
    source = dict(retainTokens=200, summarizationProvider='summary', summarizationModel='default',
                  modelPolicies=[dict(provider='small', model='shared', thresholdRatio=0.5, retainRatio=0.2,
                                      summarizationProvider='', summarizationModel='', maxTokens=512)])
    config = resolve_config(source)
    source['modelPolicies'][0]['retainRatio'] = 0.9
    policy = resolve_target_policy(config, dict(provider='small', model='shared'))
    spec = resolve_compact_spec(policy, 1000)
    assert spec['thresholdTokens'] == 500 and spec['retainTokens'] == 200
    assert spec['summarizationProvider'] == '' and spec['maxTokens'] == 512
    other = resolve_target_policy(config, dict(provider='other', model='shared'))
    assert other['retainTokens'] == 200 and other['summarizationProvider'] == 'summary'
    assert resolve_config() == dict(thresholdRatio=0.8, retainRatio=0.16, summarizationProvider='',
        summarizationModel='', maxTokens=8192, compactionRetries=1, maxOverflowRetries=1, modelPolicies=[], auto=True)
    with pytest.raises(TypeError):
        config['modelPolicies'][0]['maxTokens'] = 10
    with pytest.raises(TypeError):
        spec['target']['provider'] = 'other'


def test_distinct_route_identity_with_embedded_nul():
    config = resolve_config(dict(modelPolicies=[dict(provider='a\0b', model='c', maxTokens=1),
                                                dict(provider='a', model='b\0c', maxTokens=2)]))
    assert resolve_target_policy(config, dict(provider='a\0b', model='c'))['maxTokens'] == 1
    assert resolve_target_policy(config, dict(provider='a', model='b\0c'))['maxTokens'] == 2


@pytest.mark.parametrize('window', [0, -1, 1.5, True, None, float('inf')])
def test_invalid_capacity_is_a_target_pressure_error(window):
    policy = resolve_target_policy(resolve_config(), dict(provider='p', model='m'))
    with pytest.raises(TargetPressureConfigError) as error:
        resolve_compact_spec(policy, window)
    assert error.value.target_key == 'p/m'


class Llm:
    def __init__(self, window=1000, summary='small checkpoint'):
        self.window, self.summary, self.requests, self.resolutions = window, summary, [], []

    async def resolve_model_info(self, provider, model, signal=None):
        self.resolutions.append((provider, model, signal))
        return {} if self.window is None else dict(context=dict(contextWindow=self.window))

    async def stream(self, request):
        self.requests.append(request)
        text = self.summary(len(self.requests)) if callable(self.summary) else self.summary
        yield dict(type='text-delta', index=0, text=text)
        yield dict(type='finish', reason=dict(kind='stop'))


class Owner:
    def __init__(self, session):
        self.session = session
        self.options = SimpleNamespace(provider='fallback', model='fallback')


def setup(config=None, window=1000, turns=4, text='fixture ' * 40):
    ctx = Context()
    TokenMeter(ctx)
    llm = Llm(window)
    ctx.set_service('llm', llm)
    session = SessionStore(ctx).create('policy')
    for turn in range(1, turns + 1):
        session.append('turn/start', dict(turn=turn))
        session.append_user_message(text + ' user ' + str(turn))
        session.append('step/start', dict(turn=turn, step=1))
        if turn == 1:
            session.append('request/header', dict(header=dict(config=dict(provider='routed', model='shared')), reason='initial'))
        session.append_assistant_message(dict(role='assistant', content=[dict(type='text', text=text + ' assistant ' + str(turn))]), turn=turn, step=1)
        session.append('step/end', dict(turn=turn, step=1))
        session.append('turn/end', dict(turn=turn, reason=dict(kind='completed')))
    session.append('turn/start', dict(turn=turns + 1))
    engine = CompactionEngine(ctx=ctx, config=config)
    return ctx, llm, session, engine, Owner(session)


@pytest.mark.asyncio
async def test_routed_capacity_overrides_agent_options_and_summary_policy():
    ctx, llm, session, engine, owner = setup(dict(thresholdRatio=0.5, retainTokens=180,
        modelPolicies=[dict(provider='routed', model='shared', summarizationProvider='summary-p',
                            summarizationModel='summary-m', maxTokens=256)]))
    signal = AbortController().signal
    result = await engine.compact_if_needed(owner, 'pressure', signal)
    assert result is not None and session.surface.replace_generation == 1
    assert llm.resolutions == [('routed', 'shared', signal)]
    assert llm.requests[0]['provider'] == 'summary-p' and llm.requests[0]['maxTokens'] == 256
    assert ctx.get('tokenMeter').measure(session)['totalTokens'] < 500
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_exact_threshold_qualifies_and_capacity_missing_warns_once(caplog):
    ctx, llm, session, engine, owner = setup(dict(retainTokens=0), window=None)
    for _ in range(2):
        assert await ctx.waterfall('agent/pre-step', dict(agent=owner), lambda *_: 'next') == 'next'
    assert len([record for record in caplog.records if 'no context capacity' in record.message]) == 1
    llm.window = ctx.get('tokenMeter').measure(session)['totalTokens']
    engine.config = resolve_config(dict(thresholdRatio=1, retainTokens=0))
    assert await engine.compact_if_needed(owner) is not None
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_pressure_attempt_budget_and_oversized_envelope_fail_after_progress():
    ctx, llm, session, engine, owner = setup(dict(thresholdRatio=0.5, retainTokens=0, compactionRetries=1))
    llm.summary = lambda count: 'long first checkpoint ' * 5 if count == 1 else 'short'
    session.append('request/header', dict(header=dict(config=dict(provider='routed', model='shared'), system='x' * 3000), reason='resume'))
    with pytest.raises(RuntimeError, match='after 2 compaction attempts'):
        await engine.compact_if_needed(owner)
    assert session.surface.replace_generation == 2 and len(llm.requests) == 2
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_aborted_pre_step_does_not_prune_resolve_or_summarize():
    ctx, llm, session, engine, owner = setup()
    signal = AbortController()
    signal.abort('stop')
    assert await ctx.waterfall('agent/pre-step', dict(agent=owner, signal=signal.signal), lambda *_: 'next') == 'next'
    assert llm.resolutions == [] and llm.requests == []
    await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['UNKNOWN', 'CONTEXT_WINDOW_EXCEEDED'])
async def test_overflow_recovery_requires_real_replacement_and_has_per_agent_cap(failure):
    ctx, llm, session, engine, owner = setup(dict(thresholdRatio=1, retainTokens=0), window=None)
    llm.summary = lambda count: 'long first checkpoint ' * 5 if count == 1 else 'short'
    async def dispatch():
        return await ctx.waterfall('agent/request-error', dict(agent=owner, failure=dict(code=failure)), lambda *_: 'delegate')
    result = await dispatch()
    if failure == 'UNKNOWN':
        assert result == 'delegate' and session.surface.replace_generation == 0
    else:
        assert result == dict(kind='retry') and session.surface.replace_generation == 1
        assert llm.resolutions == []
        assert await dispatch() == 'delegate'
        ctx.emit('agent/status', dict(agent=owner, status='idle'))
        assert await dispatch() == dict(kind='retry')
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_overflow_prune_progress_survives_summary_error_and_cancellation_wins():
    ctx, llm, session, engine, owner = setup(dict(retainTokens=0))
    signal = AbortController()
    calls = []
    async def compact(agent, trigger, abort):
        seq = agent.session.surface.nodes[0]
        agent.session.append_user_message('pruned', surface_op=dict(op='replace', start=seq, end=seq), source_event_seqs=[seq])
        calls.append(trigger)
        raise RuntimeError('summary failed')
    engine.compact_if_needed = compact
    payload = dict(agent=owner, failure=dict(code='CONTEXT_WINDOW_EXCEEDED'), signal=signal.signal)
    assert await ctx.waterfall('agent/request-error', payload, lambda *_: 'delegate') == dict(kind='retry')
    ctx.emit('agent/status', dict(agent=owner, status='idle'))
    async def cancelled(agent, trigger, abort):
        await compact(agent, trigger, abort)
    async def cancel_then_fail(agent, trigger, abort):
        try:
            await cancelled(agent, trigger, abort)
        finally:
            signal.abort('stop')
    engine.compact_if_needed = cancel_then_fail
    assert await ctx.waterfall('agent/request-error', payload, lambda *_: 'delegate') == 'delegate'
    assert calls == ['context-overflow', 'context-overflow']
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_overflow_success_reset_disabled_auto_and_weak_ownership():
    ctx, llm, session, engine, owner = setup(dict(retainTokens=0))
    payload = dict(agent=owner, failure=dict(code='CONTEXT_WINDOW_EXCEEDED'))
    assert await ctx.waterfall('agent/request-error', payload, lambda *_: None) == dict(kind='retry')
    session.append('step/start', dict(turn=5, step=1))
    session.append_assistant_message(dict(role='assistant', content='success'), turn=5, step=1)
    session.append('step/end', dict(turn=5, step=1))
    assert owner not in engine._overflow_retries
    handle = weakref.ref(owner)
    del payload, owner
    gc.collect()
    assert handle() is None and not engine._overflow_retries
    await ctx.fiber.dispose()
    ctx, llm, session, engine, owner = setup(dict(auto=False))
    assert await ctx.waterfall('agent/request-error', dict(agent=owner, failure=dict(code='CONTEXT_WINDOW_EXCEEDED')), lambda *_: 'delegate') == 'delegate'
    assert session.surface.replace_generation == 0
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_plugin_injection_and_unload_remove_service_and_hooks():
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    TokenMeter(ctx)
    ctx.set_service('llm', Llm())
    fiber = await ctx.plugin(CompactionBasicPlugin)
    assert ctx.get('compaction') is not None
    await fiber.dispose()
    assert ctx.get('compaction') is None
    assert await ctx.waterfall('agent/pre-step', dict(agent=None), lambda *_: 'next') == 'next'
    await ctx.fiber.dispose()
