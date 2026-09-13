"""
1:1 Test Parity Suite for the `@deepseek-ai/dsh-session` Typert provider.
Matching reference packages/core/session/tests/typert.spec.ts.

Upstream case inventory (1 `describe`, 1 `it`):

  describe('Session Typert provider')
    it('contributes live Session lookup in either service load order')  -> PORTED

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import pytest

from dsh.cordis.context import Context
from dsh.core.session import SessionId, SessionStore
from dsh.typert import TypertRegistry


class TestSessionTypertProvider:
    """
    reference `describe('Session Typert provider')`.
    """

    @pytest.mark.asyncio
    async def test_contributes_live_session_lookup_in_either_service_load_order(self) -> None:
        """
        reference `it('contributes live Session lookup in either service load
        order')` (typert.spec.ts:6-24), step for step:

          1. `const ctx = new Context()`
          2. `const sessionFiber = ctx.plugin(SessionStore)` then
             `await sessionFiber` (the store loads BEFORE the registry).
          3. `await ctx.plugin(TypertRegistry)`
          4. `const session = ctx.sessions.create(SessionId('remote-session'))`
          5. `const lookup = ctx.typert.lookups.get('session')` with
             `expect(lookup).toMatchObject({ parameter: 'session',
             wire: 'sessionId',
             hostTypeSymbol: '@deepseek-ai/dsh-session#Session',
             wireTypeSymbol: '@deepseek-ai/dsh-session/types#SessionId' })`
          6. `expect(lookup?.resolve(session.id)).toBe(session)` — IDENTITY, not a
             copy.
          7. `await sessionFiber.dispose()` then
             `expect(ctx.typert.lookups.get('session')).toBeUndefined()` — the
             registration is reversibly scoped to the owning fiber.
        """
        ctx = Context()
        # 2. The store plugin is loaded first, before any Typert registry exists:
        #    its contribution has to be delayed until `typert` is provided.
        session_fiber = ctx.plugin(SessionStore)
        await session_fiber
        assert ctx.get("typert") is None

        # 3. The registry arrives afterwards and activates the delayed inject.
        await ctx.plugin(TypertRegistry)

        # 4. A session created after both services are live.
        session = ctx.get("sessions").create(SessionId("remote-session"))

        # 5. The lookup metadata, field for field (`toMatchObject`).
        lookup = ctx.typert.lookups.get("session")
        assert lookup is not None
        assert lookup.to_dict() == {
            "parameter": "session",
            "wire": "sessionId",
            "hostTypeSymbol": "@deepseek-ai/dsh-session#Session",
            "wireTypeSymbol": "@deepseek-ai/dsh-session/types#SessionId",
        }
        assert lookup.hostTypeSymbol == "@deepseek-ai/dsh-session#Session"
        assert lookup.wireTypeSymbol == "@deepseek-ai/dsh-session/types#SessionId"

        # 6. Identity resolution through the live store entry.
        assert lookup.resolve(session.id) is session
        # An unknown wire id resolves to `undefined`.
        assert lookup.resolve(SessionId("absent-session")) is None

        # 7. Disposing the owning fiber withdraws the registration again.
        await session_fiber.dispose()
        assert ctx.typert.lookups.get("session") is None

        # The same contract holds in the REVERSE service load order (the
        # upstream case title: "either service load order"): with the registry
        # already live, the store's delayed contribution activates immediately.
        reverse_ctx = Context()
        await reverse_ctx.plugin(TypertRegistry)
        reverse_fiber = reverse_ctx.plugin(SessionStore)
        await reverse_fiber
        reverse_session = reverse_ctx.get("sessions").create(SessionId("reverse-session"))
        reverse_lookup = reverse_ctx.typert.lookups.get("session")
        assert reverse_lookup is not None
        assert reverse_lookup.to_dict() == {
            "parameter": "session",
            "wire": "sessionId",
            "hostTypeSymbol": "@deepseek-ai/dsh-session#Session",
            "wireTypeSymbol": "@deepseek-ai/dsh-session/types#SessionId",
        }
        assert reverse_lookup.resolve(reverse_session.id) is reverse_session
        await reverse_fiber.dispose()
        assert reverse_ctx.typert.lookups.get("session") is None
