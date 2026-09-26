"""
1:1 mapping of `reference/packages/feedback/message-feedback/tests/invariant.spec.ts`
(`message-feedback invariant companion`):

  - ``removes its registry contribution when its fiber is disposed (HMR safety)``

The companion installs no runtime check — the private typed writer owns current
row mutations and the domain schema validates rows on reopen — but it must still
reserve the package name, so a second registration is loud and an HMR reload
after disposal succeeds.
"""

import pytest

from dsh.diagnostics.invariants import InvariantRegistry
from dsh.feedback import invariant as message_feedback_invariant

from .helpers import setup_harness

PACKAGE_NAME = "@deepseek-ai/dsh-message-feedback"


@pytest.mark.asyncio
async def test_removes_its_registry_contribution_when_its_fiber_is_disposed():
    harness = await setup_harness()
    try:
        ctx = harness.ctx
        InvariantRegistry(ctx)
        fiber = ctx.plugin(message_feedback_invariant)

        with pytest.raises(ValueError, match="already registered"):
            ctx.invariants.register(PACKAGE_NAME, lambda *args: None)

        await fiber.dispose()
        reloaded = ctx.plugin(message_feedback_invariant)
        assert reloaded is not None
        assert PACKAGE_NAME in ctx.invariants.registrations
    finally:
        await harness.dispose()
