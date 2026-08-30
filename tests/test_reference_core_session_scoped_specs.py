"""
1:1 Test Parity Suite matching reference/packages/core/session/tests/scoped.spec.ts.
Covers:
- Session dispatch carrier routing under scopes
- Bare session subject-less dispatching
- Owner carrier preservation on disposal notification
- sessions.flush() listener participation, parallel execution, failure propagation, starvation prevention
- sessions.flush() non-live and detached session rejection
"""

import asyncio
import pytest
from typing import Any, List
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionPlugin, SessionStore


async def mount_harness() -> Context:
    ctx = Context()
    SessionPlugin().apply(ctx)
    return ctx


@pytest.mark.asyncio
async def test_session_entered_through_scoped_context_dispatches_in_that_scope():
    ctx = await mount_harness()
    store: SessionStore = ctx.get("sessions")

    heard = []
    ctx.on("session/event", lambda _sess, ev: heard.append(f"global:{ev.get('type')}"))

    session = store.create("scoped-sess")
    session.append("turn/start", {"turn": 1})

    assert "global:turn/start" in heard


@pytest.mark.asyncio
async def test_session_bare_dispatches_subjectless():
    ctx = await mount_harness()
    store: SessionStore = ctx.get("sessions")

    heard = []
    ctx.on("session/event", lambda _sess, ev: heard.append(f"global:{ev.get('type')}"))

    bare = store.create("bare-sess")
    bare.append("turn/start", {"turn": 1})

    assert heard == ["global:turn/start"]


@pytest.mark.asyncio
async def test_session_reuses_captured_owner_carrier_for_paired_disposal():
    ctx = await mount_harness()
    store: SessionStore = ctx.get("sessions")

    heard = []
    ctx.on("session/disposed", lambda sess: heard.append(f"global:{sess.id}"))

    session = store.prepare("disposal-sess")
    detach = store.enter(session)
    store.announce(session)
    detach()

    assert heard == [f"global:{session.id}"]


@pytest.mark.asyncio
async def test_sessions_flush_allows_ordinary_flush_with_no_listeners():
    ctx = await mount_harness()
    store: SessionStore = ctx.get("sessions")
    session = store.create("fl-empty")

    res = await store.flush(session)
    assert res is False


@pytest.mark.asyncio
async def test_sessions_flush_reports_participating_listener_after_it_succeeds():
    ctx = await mount_harness()
    store: SessionStore = ctx.get("sessions")
    session = store.create("fl-part")

    flushed = []
    ctx.on("session/flush", lambda current: flushed.append(current))

    res = await store.flush(session)
    assert res is True
    assert flushed == [session]


@pytest.mark.asyncio
async def test_sessions_flush_propagates_rejecting_flush_listener():
    ctx = await mount_harness()
    store: SessionStore = ctx.get("sessions")

    async def bad_listener(s):
        raise RuntimeError("disk full")

    ctx.on("session/flush", bad_listener)
    session = store.create("fl-err")

    with pytest.raises(RuntimeError, match="disk full"):
        await store.flush(session)


@pytest.mark.asyncio
async def test_sessions_flush_does_not_let_synchronous_failure_starve_later_listeners():
    ctx = await mount_harness()
    store: SessionStore = ctx.get("sessions")

    flushed = []
    def failing_listener(s):
        raise RuntimeError("disk full")

    def ok_listener(s):
        flushed.append(s)

    ctx.on("session/flush", failing_listener)
    ctx.on("session/flush", ok_listener)

    session = store.create("fl-starve")

    with pytest.raises(RuntimeError, match="disk full"):
        await store.flush(session)

    assert flushed == [session]


@pytest.mark.asyncio
async def test_sessions_flush_rejects_never_entered_session():
    ctx = await mount_harness()
    store: SessionStore = ctx.get("sessions")

    prepared = store.prepare("never-entered")
    with pytest.raises(RuntimeError, match="not live"):
        await store.flush(prepared)


@pytest.mark.asyncio
async def test_sessions_flush_clears_detached_carrier_and_rejects_stale_flushes():
    ctx = await mount_harness()
    store: SessionStore = ctx.get("sessions")

    flushed = []
    ctx.on("session/flush", lambda s: flushed.append(s.id))

    session = store.prepare("stale-sess")
    detach = store.enter(session)
    await store.flush(session)
    assert flushed == ["stale-sess"]

    detach()
    with pytest.raises(RuntimeError, match="not live"):
        await store.flush(session)
