"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session scoped dispatch carriers and flush.
Matching packages/core/session/tests/scoped.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
from typing import Any, List
import pytest

from dsh.cordis.context import Context
from dsh.core.scope import Scope, create_scope, scope_of
from dsh.core.session import Session, SessionPlugin, SessionStore


async def mount_harness() -> Context:
    ctx = Context()
    SessionPlugin().apply(ctx)
    return ctx


async def mint_scope(ctx: Context, name: str) -> Scope:
    key = {"name": name}
    scope = create_scope(ctx, key)
    return scope


def key_of(scope: Scope) -> Any:
    return scope_of(scope.ctx)


class TestSessionDispatchCarriers:
    @pytest.mark.asyncio
    async def test_session_entered_through_scoped_context_dispatches_in_that_scope(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")

        heard: List[str] = []
        ctx.on("session/event", lambda _s, ev: heard.append(f"global:{ev.get('type')}"))

        session = store.create("scoped-sess")
        session.append("turn/start", {"turn": 1})

        assert "global:turn/start" in heard

    @pytest.mark.asyncio
    async def test_bare_session_dispatches_subjectless(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")

        heard: List[str] = []
        ctx.on("session/event", lambda _s, ev: heard.append(f"global:{ev.get('type')}"))

        bare = store.create("bare-sess")
        bare.append("turn/start", {"turn": 1})

        assert heard == ["global:turn/start"]

    @pytest.mark.asyncio
    async def test_reuses_captured_owner_carrier_for_paired_disposal(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")

        heard: List[str] = []
        ctx.on("session/disposed", lambda s: heard.append(f"global:{s.id}"))

        session = store.prepare("disposal-sess")
        detach = store.enter(session)
        store.announce(session)
        detach()

        assert heard == [f"global:{session.id}"]


class TestSessionsFlush:
    @pytest.mark.asyncio
    async def test_allows_ordinary_flush_with_no_listeners(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")
        session = store.create("fl-empty")

        res = await store.flush(session)
        assert res is False

    @pytest.mark.asyncio
    async def test_reports_participating_listener_after_it_succeeds(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")
        session = store.create("fl-part")

        flushed: List[Session] = []
        ctx.on("session/flush", lambda current: flushed.append(current))

        res = await store.flush(session)
        assert res is True
        assert flushed == [session]

    @pytest.mark.asyncio
    async def test_dispatches_session_flush_and_awaits_all_listeners(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")
        flushed: List[str] = []

        async def global_listener(sess: Session) -> None:
            await asyncio.sleep(0.001)
            flushed.append(f"global:{sess.id}")

        ctx.on("session/flush", global_listener)

        owned = store.create("owned")
        bare = store.create("bare")
        await store.flush(owned)
        await store.flush(bare)

        assert f"global:{owned.id}" in flushed
        assert f"global:{bare.id}" in flushed

    @pytest.mark.asyncio
    async def test_propagates_rejecting_flush_listener(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")

        async def bad_listener(s: Session) -> None:
            raise RuntimeError("disk full")

        ctx.on("session/flush", bad_listener)
        session = store.create("fl-err")

        with pytest.raises(RuntimeError, match="disk full"):
            await store.flush(session)

    @pytest.mark.asyncio
    async def test_does_not_let_synchronous_failure_starve_later_listeners(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")

        flushed: List[Session] = []

        def failing_listener(s: Session) -> None:
            raise RuntimeError("disk full")

        def ok_listener(s: Session) -> None:
            flushed.append(s)

        ctx.on("session/flush", failing_listener)
        ctx.on("session/flush", ok_listener)

        session = store.create("fl-starve")

        with pytest.raises(RuntimeError, match="disk full"):
            await store.flush(session)

        assert flushed == [session]

    @pytest.mark.asyncio
    async def test_waits_for_slower_flush_listeners_before_reporting_failure(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")
        gate = asyncio.Event()
        slow_started = False
        settled = False

        async def bad_listener(s: Session) -> None:
            raise RuntimeError("disk full")

        async def slow_listener(s: Session) -> None:
            nonlocal slow_started
            slow_started = True
            await gate.wait()

        ctx.on("session/flush", bad_listener)
        ctx.on("session/flush", slow_listener)

        session = store.create("fl-slow")

        async def run_flush():
            nonlocal settled
            try:
                await store.flush(session)
            finally:
                settled = True

        task = asyncio.create_task(run_flush())
        await asyncio.sleep(0.01)
        assert slow_started is True
        assert settled is False

        gate.set()
        with pytest.raises(RuntimeError, match="disk full"):
            await task
        assert settled is True

    @pytest.mark.asyncio
    async def test_rejects_never_entered_session(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")

        prepared = store.prepare("never-entered")
        with pytest.raises(RuntimeError, match="not live"):
            await store.flush(prepared)

    @pytest.mark.asyncio
    async def test_clears_detached_carrier_and_rejects_stale_flushes(self):
        ctx = await mount_harness()
        store: SessionStore = ctx.get("sessions")

        flushed: List[str] = []
        ctx.on("session/flush", lambda s: flushed.append(s.id))

        session = store.prepare("stale-sess")
        detach = store.enter(session)
        await store.flush(session)
        assert flushed == ["stale-sess"]

        detach()
        with pytest.raises(RuntimeError, match="not live"):
            await store.flush(session)

    @pytest.mark.asyncio
    async def test_key_of_sanity_distinct_scopes_carry_distinct_keys(self):
        ctx = await mount_harness()
        a = await mint_scope(ctx, "a")
        b = await mint_scope(ctx, "b")
        assert key_of(a) != key_of(b)
