"""
1:1 parity suite for the `@deepseek-ai/dsh-sandbox-policy` invariant companion
(`dsh/sandbox/sandbox_policy_invariant.py`).

Upstream is reference/packages/sandbox/sandbox-policy/tests/invariant.spec.ts:
the companion accepts every durable mode in the closed vocabulary, ignores
unrelated event streams, rejects an unknown mode attributed to its package, and
re-sweeps existing history when it loads after the sessions.
"""

from typing import Any, Dict

import pytest

from dsh.core.session import SessionStore
from dsh.cordis.context import Context
from dsh.diagnostics.invariants import InvariantError, InvariantRegistry
from dsh.sandbox.sandbox_policy_invariant import apply as apply_sandbox_policy_invariant

PACKAGE_NAME = "@deepseek-ai/dsh-sandbox-policy"


class _Companion:
    """The companion mounted as an ordinary plugin (name + inject + apply)."""

    name = "sandbox-policy-invariant"
    inject = ["invariants"]

    def apply(self, ctx: Any) -> None:
        return apply_sandbox_policy_invariant(ctx)


async def setup() -> Context:
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(InvariantRegistry, {"enabled": True})
    await ctx.plugin(_Companion())
    return ctx


def mode_event(mode: str) -> Dict[str, Any]:
    return {"type": "sandbox/mode", "seq": 0, "time": 0, "data": {"mode": mode}}


@pytest.mark.parametrize("mode", ["read-only", "workspace-write", "danger-full-access"])
@pytest.mark.asyncio
async def test_accepts_the_durable_mode(mode):
    ctx = await setup()
    ctx.emit("session/event", object(), mode_event(mode))


@pytest.mark.asyncio
async def test_ignores_unrelated_event_streams():
    ctx = await setup()
    ctx.emit("session/event", object(), {"type": "turn/start", "seq": 0, "time": 0, "data": {}})
    ctx.emit("tools/change")


@pytest.mark.asyncio
async def test_rejects_and_attributes_an_unknown_durable_sandbox_mode():
    ctx = await setup()
    with pytest.raises(InvariantError) as raised:
        ctx.emit("session/event", object(), mode_event("host-root"))
    assert raised.value.code == "INVARIANT"
    assert raised.value.package_name == PACKAGE_NAME
    assert 'sandbox/mode carries unknown mode "host-root"' in str(raised.value)


@pytest.mark.asyncio
async def test_rejects_an_unknown_mode_already_present_on_late_registration():
    ctx = Context()
    await ctx.plugin(SessionStore)
    ctx.get("sessions").create("late-invalid").append("sandbox/mode", {"mode": "host-root"})
    await ctx.plugin(InvariantRegistry, {"enabled": True})

    failure = None
    try:
        await ctx.plugin(_Companion())
    except Exception as error:  # noqa: BLE001 - the companion's failure is the assertion
        failure = error
    assert isinstance(failure, InvariantError)
    assert failure.code == "INVARIANT"
    assert failure.package_name == PACKAGE_NAME
