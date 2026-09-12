"""
1:1 parity suite for the `@deepseek-ai/dsh-session-log-deepseek` invariant
companion (`dsh/session/session_log_deepseek_invariant.py`).

Upstream is
reference/packages/session/session-log-deepseek/tests/invariant.spec.ts.
The companion validates that an acceptance watermark names its containing
session and identifies an earlier event in the same log, re-sweeps history when
it loads late, and admits an inherited parent watermark replayed from a fork
seed.
"""

from typing import Any, Dict

import pytest

from dsh.core.session import SessionStore
from dsh.cordis.context import Context
from dsh.diagnostics.invariants import InvariantError, InvariantRegistry
from dsh.session.session_log_deepseek import ACCEPTED_EVENT_TYPE
from dsh.session.session_log_deepseek_invariant import apply as apply_session_log_invariant

PACKAGE_NAME = "@deepseek-ai/dsh-session-log-deepseek"


class _Companion:
    """The companion mounted as an ordinary plugin (name + inject + apply)."""

    name = "session-log-deepseek-invariant"
    inject = ["invariants"]

    def apply(self, ctx: Any) -> None:
        apply_session_log_invariant(ctx)


async def setup() -> Dict[str, Any]:
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(InvariantRegistry)
    await ctx.plugin(_Companion())
    return {"ctx": ctx}


@pytest.mark.asyncio
async def test_accepts_a_watermark_naming_an_earlier_event_in_its_containing_session():
    test = await setup()
    session = test["ctx"].get("sessions").create("valid")
    session.append("turn/start", {"turn": 1})
    session.append(ACCEPTED_EVENT_TYPE, {"sessionId": session.id, "throughSeq": 0})


@pytest.mark.asyncio
async def test_rejects_a_live_watermark_for_another_session_or_a_non_earlier_sequence():
    test = await setup()
    sessions = test["ctx"].get("sessions")

    wrong_id = sessions.create("wrong-id")
    wrong_id.append("turn/start", {"turn": 1})
    with pytest.raises(InvariantError) as raised:
        wrong_id.append(ACCEPTED_EVENT_TYPE, {"sessionId": "other", "throughSeq": 0})
    assert raised.value.code == "INVARIANT"
    assert raised.value.package_name == PACKAGE_NAME

    wrong_seq = sessions.create("wrong-seq")
    wrong_seq.append("turn/start", {"turn": 1})
    with pytest.raises(InvariantError) as raised_seq:
        wrong_seq.append(ACCEPTED_EVENT_TYPE, {"sessionId": wrong_seq.id, "throughSeq": 1})
    assert raised_seq.value.code == "INVARIANT"
    assert raised_seq.value.package_name == PACKAGE_NAME


@pytest.mark.asyncio
async def test_validates_existing_history_when_the_invariant_loads_after_the_session():
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(InvariantRegistry)
    session_id = "late-invalid"
    ctx.get("sessions").create(
        session_id,
        {
            "seed": [
                {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
                {
                    "type": ACCEPTED_EVENT_TYPE,
                    "seq": 1,
                    "time": 2,
                    "data": {"sessionId": session_id, "throughSeq": 1},
                },
            ]
        },
    )

    failure = None
    try:
        await ctx.plugin(_Companion())
    except Exception as error:  # noqa: BLE001 - the companion's failure is the assertion
        failure = error
    assert isinstance(failure, InvariantError)
    assert failure.code == "INVARIANT"
    assert failure.package_name == PACKAGE_NAME


@pytest.mark.asyncio
async def test_allows_an_inherited_parent_watermark_inside_a_fork_seed():
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(InvariantRegistry)
    parent_id = "fork-parent"
    child_id = "fork-child"
    ctx.get("sessions").create(
        child_id,
        {
            "seed": [
                {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
                {
                    "type": ACCEPTED_EVENT_TYPE,
                    "seq": 1,
                    "time": 2,
                    "data": {"sessionId": parent_id, "throughSeq": 0},
                },
            ],
            "meta": {"parentSession": parent_id, "seedLength": 2},
        },
    )

    assert await ctx.plugin(_Companion()) is not None
