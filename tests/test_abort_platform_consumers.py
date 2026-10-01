"""Regress actual platform/Inspect observations and native cancellation consumers."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController, AbortError, AbortSignal, abort_reason_error
from dsh.core.cancellation import subscribe_abort
from dsh.core.session.json import UNDEFINED
from dsh.core.tools import _FusedSignal
from dsh.compaction.transaction import check_cancel
from dsh.interaction.commands import abort_error
from dsh.llm.deepseek_api_extensions import _abort_error
from dsh.session.preparations import throw_aborted, observe_queued_abort
from dsh.terminal.service import check_signal
from scripts.oracles.abort_python import observe

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/fixtures/abort-source-observations.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
async def test_native_abort_and_inspect_match_actual_platform_observations():
    assert await observe() == FIXTURE['observations']


def test_platform_observation_inputs_are_pinned():
    assert FIXTURE['target_upstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert len(FIXTURE['observations']) == 56
    for path, expected in FIXTURE['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == expected


@pytest.mark.parametrize('reason', [None, False, 0, '', 'stop', {'nested': [None, True]}])
@pytest.mark.parametrize('check', [lambda s: s.throwIfAborted(), check_cancel, throw_aborted, check_signal])
def test_native_consumers_preserve_arbitrary_reason_identity(reason, check):
    signal = AbortSignal.abort(reason)
    with pytest.raises(ThrownValueError) as caught:
        check(signal)
    assert caught.value.value is reason and caught.value.reason is reason


@pytest.mark.parametrize('check', [lambda s: s.throwIfAborted(), check_cancel, throw_aborted, check_signal])
def test_native_consumers_throw_the_same_default_abort_error(check):
    signal = AbortSignal.abort()
    with pytest.raises(AbortError) as caught:
        check(signal)
    assert caught.value is signal.reason
    assert (caught.value.name, caught.value.code, caught.value.message) == ('AbortError', 20, 'This operation was aborted')


@pytest.mark.parametrize('reason', [None, False, 0, '', 'stop', {'nested': [None]}])
def test_extension_prepare_error_keeps_reason_and_commands_keep_original_normalization(reason):
    signal = AbortSignal.abort(reason)
    error = _abort_error(signal)
    assert isinstance(error, ThrownValueError) and error.value is reason
    command_error = abort_error(signal)
    assert str(command_error) == (reason if isinstance(reason, str) else 'command aborted')


def test_unset_explicit_undefined_and_null_are_distinct_at_abort():
    ordinary, undefined, null = AbortController(), AbortController(), AbortController()
    ordinary.abort()
    undefined.abort(UNDEFINED)
    null.abort(None)
    assert isinstance(ordinary.signal.reason, AbortError) and isinstance(undefined.signal.reason, AbortError)
    assert ordinary.signal.reason is not undefined.signal.reason
    assert null.signal.reason is None
    assert abort_error(ordinary.signal) is ordinary.signal.reason


def test_raw_events_and_python_subscriptions_have_different_settled_state_contracts():
    c, events, native = AbortController(), [], []
    c.signal.addEventListener('abort', events.append, dict(once=True))
    c.abort(None)
    assert events[0].type == 'abort' and events[0].target is c.signal
    assert not c.signal._dom_listeners and not c.signal._listeners
    c.signal.addEventListener('abort', events.append)
    remove = subscribe_abort(c.signal, native.append)
    assert len(events) == 1 and native == [None]
    remove()


def test_default_and_exception_abort_identity_survives_python_relay():
    for reason in (AbortError(), RuntimeError('caller')):
        caller, follower = AbortController(), AbortController()
        remove = subscribe_abort(caller.signal, follower.abort)
        caller.abort(reason)
        caller.abort('ignored')
        assert follower.signal.reason is reason
        assert abort_reason_error(follower.signal) is reason
        remove()
        assert not caller.signal._listeners


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', [None, False, 0, 'cancelled'])
async def test_queued_session_abort_keeps_reason_without_cancelling_provider(reason):
    c, entered, release, disposed = AbortController(), asyncio.Event(), asyncio.Event(), []
    async def provider():
        entered.set()
        try:
            await release.wait()
            return 'late source'
        finally:
            disposed.append(True)
    job = asyncio.create_task(provider())
    view = asyncio.create_task(observe_queued_abort(job, c.signal))
    await entered.wait()
    c.abort(reason)
    try:
        with pytest.raises(ThrownValueError) as caught:
            await asyncio.wait_for(view, 1)
        assert caught.value.value is reason
        assert not job.done() and not c.signal._listeners
    finally:
        release.set()
        assert await job == 'late source'
    assert disposed == [True]


def test_historical_external_missing_reason_keeps_adapter_error():
    error = abort_reason_error(SimpleNamespace(aborted=True))
    assert type(error) is RuntimeError and str(error) == 'operation aborted'


@pytest.mark.asyncio
async def test_fused_python_wait_adapter_and_raw_event_ownership():
    caller, wrapper = AbortController(), AbortController()
    signal, events = _FusedSignal(caller.signal, wrapper.signal), []
    signal.addEventListener('abort', events.append, dict(once=True))
    waiter = asyncio.create_task(signal.wait_aborted())
    await asyncio.sleep(0)
    assert not waiter.done()
    wrapper.abort(None)
    await asyncio.wait_for(waiter, 1)
    assert len(events) == 1 and events[0].target is signal and events[0].currentTarget is signal
    assert not signal._dom_listeners and not caller.signal._listeners and not wrapper.signal._listeners
    with pytest.raises(ThrownValueError) as caught:
        signal.throwIfAborted()
    assert caught.value.value is None
    signal.dispose()
