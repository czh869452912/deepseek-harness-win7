"""
1:1 parity suite for the `@deepseek-ai/dsh-commands` invariant companion
(`dsh/interaction/invariant.py`).

Upstream is reference/packages/interaction/commands/tests/invariant.spec.ts.
The companion validates that `command/run` and `command/done` pair by
commandId within one session log, that a repeated run id is rejected, and that
a `command/done` source reference points at an earlier non-command domain
event.
"""

import asyncio
from typing import Any, Dict

import pytest

from dsh.core.session import SessionStore
from dsh.cordis.context import Context
from dsh.diagnostics.invariants import InvariantError, InvariantRegistry
from dsh.interaction.invariant import apply as apply_commands_invariant


class _Companion:
    """The companion mounted as an ordinary plugin (name + inject + apply)."""

    name = "commands-invariant"
    inject = ["invariants"]

    def apply(self, ctx: Any) -> None:
        apply_commands_invariant(ctx)


async def mount(install_companion: bool = True) -> Dict[str, Any]:
    ctx = Context()
    await ctx.plugin(SessionStore)
    session = ctx.get("sessions").create("commands-invariant")
    await ctx.plugin(InvariantRegistry)
    if install_companion:
        await ctx.plugin(_Companion())
    return {"ctx": ctx, "session": session}


def append_run(session: Any, command_id: str) -> None:
    session.append(
        "command/run",
        {"commandId": command_id, "name": "linked", "args": "", "source": {"kind": "user"}},
    )


@pytest.mark.asyncio
async def test_accepts_a_success_outcome_linked_to_an_earlier_non_command_domain_event():
    test = await mount()
    session = test["session"]
    source = session.append("turn/start", {"turn": 1})
    append_run(session, "cmd-valid")

    session.append(
        "command/done",
        {"commandId": "cmd-valid", "kind": "success", "sourceEventSeq": source["seq"]},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source_event_seq", [-1, 1.5, 1])
async def test_rejects_invalid_or_non_prior_source_event_seq(source_event_seq):
    test = await mount()
    session = test["session"]
    append_run(session, "cmd-invalid")

    with pytest.raises(InvariantError) as raised:
        session.append(
            "command/done",
            {"commandId": "cmd-invalid", "kind": "success", "sourceEventSeq": source_event_seq},
        )

    assert raised.value.code == "INVARIANT"
    assert raised.value.package_name == "@deepseek-ai/dsh-commands"


@pytest.mark.asyncio
async def test_rejects_an_error_settlement_carrying_a_success_only_source_reference():
    test = await mount()
    session = test["session"]
    source = session.append("turn/start", {"turn": 1})
    append_run(session, "cmd-error-source")

    with pytest.raises(InvariantError) as raised:
        session.append(
            "command/done",
            {
                "commandId": "cmd-error-source",
                "kind": "error",
                "text": "failed",
                "sourceEventSeq": source["seq"],
            },
        )

    assert raised.value.code == "INVARIANT"
    assert raised.value.package_name == "@deepseek-ai/dsh-commands"


@pytest.mark.asyncio
async def test_attributes_an_invalid_durable_prefix_during_late_companion_loading():
    test = await mount(install_companion=False)
    ctx = test["ctx"]
    session = test["session"]
    append_run(session, "cmd-late")
    session.append(
        "command/done", {"commandId": "cmd-late", "kind": "success", "sourceEventSeq": 0}
    )

    # The reference `await ctx.plugin(...)` rejects; the port records the
    # installation failure on the fiber, which `assert_active(check_error=True)`
    # re-raises (the same failure surface every other failed plugin install uses).
    fiber = ctx.plugin(_Companion())
    assert fiber.error is not None
    with pytest.raises(InvariantError) as raised:
        fiber.assert_active(check_error=True)

    assert raised.value.code == "INVARIANT"
    assert raised.value.package_name == "@deepseek-ai/dsh-commands"


@pytest.mark.asyncio
async def test_rejects_a_repeated_command_run_id_and_a_done_without_its_run():
    test = await mount()
    session = test["session"]
    append_run(session, "cmd-dup")

    with pytest.raises(InvariantError):
        append_run(session, "cmd-dup")

    with pytest.raises(InvariantError):
        session.append("command/done", {"commandId": "cmd-unknown", "kind": "success"})
