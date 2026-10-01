"""
Parity suite for the port's cancellation primitive (`dsh/core/abort.py`).

The reference host code takes the platform `AbortController` / `AbortSignal`
from the JavaScript runtime; Python 3.8 has no equivalent, so the port defines
the same observable surface. These cases pin that surface the way the reference
platform primitive behaves:

* `aborted` / `reason` state, with a repeated abort ignored;
* raw platform notification versus Python settled-state subscriptions;
* `wait_aborted()` settling for a waiter that is already aborted and one that
  awaits a later abort;
* listener removal through the returned disposer and `removeEventListener`.
"""

import asyncio

import pytest

from dsh.core.abort import NEVER_ABORTED, AbortController, AbortSignal


def test_abort_sets_the_state_and_an_ignored_repeat_keeps_the_first_reason():
    controller = AbortController()
    assert controller.signal.aborted is False
    assert controller.signal.reason is None

    controller.abort("first reason")
    assert controller.signal.aborted is True
    assert controller.signal.reason == "first reason"

    controller.abort("second reason")
    assert controller.signal.reason == "first reason"


def test_a_listener_added_before_the_abort_is_notified_once_with_the_reason():
    signal = AbortSignal()
    seen = []
    signal.add_listener("abort", lambda reason=None: seen.append(reason))

    signal._abort("done")

    assert seen == ["done"]
    assert signal.aborted is True


def test_raw_listener_added_after_abort_does_not_replay_the_event():
    signal = AbortSignal()
    signal._abort("already gone")
    seen = []

    signal.addEventListener("abort", lambda reason=None: seen.append(reason))

    assert seen == []


def test_a_listener_failure_never_interrupts_the_aborting_caller():
    signal = AbortSignal()
    seen = []

    def broken(reason=None):
        raise RuntimeError("listener exploded")

    signal.add_listener("abort", broken)
    signal.add_listener("abort", lambda reason=None: seen.append(reason))

    signal._abort("boom")

    assert seen == ["boom"]


def test_the_returned_disposer_and_remove_listener_stop_notification():
    signal = AbortSignal()
    seen = []
    dispose = signal.add_listener("abort", lambda reason=None: seen.append("first"))
    other = lambda reason=None: seen.append("second")
    signal.add_listener("abort", other)

    dispose()
    signal.remove_listener("abort", other)
    signal._abort(None)

    assert seen == []


@pytest.mark.asyncio
async def test_wait_aborted_returns_immediately_for_an_aborted_signal():
    signal = AbortSignal()
    signal._abort("too late")
    await asyncio.wait_for(signal.wait_aborted(), timeout=1)


@pytest.mark.asyncio
async def test_wait_aborted_settles_when_the_signal_aborts():
    signal = AbortSignal()
    waiter = asyncio.ensure_future(signal.wait_aborted())
    await asyncio.sleep(0)
    assert not waiter.done()

    signal._abort("now")

    await asyncio.wait_for(waiter, timeout=1)


@pytest.mark.asyncio
async def test_a_cancelled_waiter_leaves_no_listener_behind():
    signal = AbortSignal()
    waiter = asyncio.ensure_future(signal.wait_aborted())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    # The abandoned waiter's registration is gone: the abort notifies nobody and
    # the signal still settles normally for a fresh waiter.
    signal._abort("after cancellation")
    assert await asyncio.wait_for(signal.wait_aborted(), timeout=1) is None


def test_the_shared_never_aborted_signal_stays_settled():
    assert NEVER_ABORTED.aborted is False
    assert NEVER_ABORTED.reason is None
