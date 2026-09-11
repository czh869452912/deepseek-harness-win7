"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session/invariant.
Matching packages/core/session/tests/invariant.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List
import pytest

from dsh.cordis.context import Context
from dsh.core.scope import create_scope, scope_target
from dsh.core.session import SessionId, SessionPlugin, SessionStore
from dsh.core.session.invariant import SessionInvariantPlugin
from dsh.core.session.repair import TOOL_NOT_STARTED
from dsh.diagnostics.invariants import InvariantError, InvariantRegistry
from dsh.llm.message import (
    create_message,
    create_tool_result_message,
    create_user_message,
    freeze_message,
)


async def setup_env() -> Dict[str, Any]:
    ctx = Context()
    SessionPlugin().apply(ctx)
    InvariantRegistry(ctx)
    plugin = SessionInvariantPlugin()
    plugin.apply(ctx)
    return {"ctx": ctx, "plugin": plugin}


class TestSessionLogInvariants:
    @pytest.mark.asyncio
    async def test_keeps_registration_global_when_companion_mounted_under_scope(self):
        ctx = Context()
        SessionPlugin().apply(ctx)
        InvariantRegistry(ctx)

        scoped = create_scope(ctx, {})
        SessionInvariantPlugin().apply(scoped.ctx)

        sessions: SessionStore = ctx.get("sessions")
        session = sessions.create(SessionId("global-under-scoped-invariants"))
        session.append("turn/start", {"turn": 1})
        session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

    @pytest.mark.asyncio
    async def test_accepts_a_well_formed_turn_step_and_tool_sequence(self):
        env = await setup_env()
        ctx: Context = env["ctx"]
        sessions: SessionStore = ctx.get("sessions")
        session = sessions.create()

        session.append("turn/start", {"turn": 1})
        session.append(
            "user/message",
            create_user_message({
                "content": [{"type": "text", "text": "hi"}],
                "source": {"kind": "user"},
            }),
            surface_op="append",
        )
        session.append("step/start", {"turn": 1, "step": 1})
        session.append("assistant/chunk", {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "h"}})
        session.append(
            "assistant/message",
            {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "tool-call", "id": "c1", "name": "echo", "arguments": "{}"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op="append",
        )
        session.append("tool/call", {"turn": 1, "step": 1, "callId": "c1", "name": "echo", "arguments": "{}"})
        session.append(
            "tool/result",
            {
                "turn": 1,
                "step": 1,
                "message": create_tool_result_message({
                    "callId": "c1",
                    "content": [],
                    "isError": False,
                }),
            },
            surface_op="append",
        )
        session.append("step/end", {"turn": 1, "step": 1})
        session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

    @pytest.mark.asyncio
    async def test_applies_committed_transition_after_another_postcommit_observer_throws(self):
        env = await setup_env()
        ctx: Context = env["ctx"]
        warnings: List[str] = []

        class MockLogger:
            def warn(self, message: Any) -> None:
                warnings.append(str(message))

        ctx.logger = MockLogger()
        sessions: SessionStore = ctx.get("sessions")
        session = sessions.create(SessionId("postcommit-peer"))

        def hostile_observer(*args):
            raise RuntimeError("hostile observer")

        ctx.on("session/event", hostile_observer, prepend=True)

        session.append("turn/start", {"turn": 1})
        session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
        assert len(warnings) == 2

    @pytest.mark.asyncio
    async def test_enforces_turn_numbering_and_core_execution_enclosure(self):
        env1 = await setup_env()
        sessions1: SessionStore = env1["ctx"].get("sessions")
        open_s = sessions1.create()
        open_s.append("turn/start", {"turn": 1})
        with pytest.raises(InvariantError, match=r"turn 1 is still open"):
            open_s.append("turn/start", {"turn": 2})
        with pytest.raises(InvariantError, match=r"does not match open turn 1"):
            open_s.append("turn/end", {"turn": 2, "reason": {"kind": "completed"}})

        env2 = await setup_env()
        sessions2: SessionStore = env2["ctx"].get("sessions")
        second = sessions2.create()
        second.append("turn/start", {"turn": 1})
        second.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
        with pytest.raises(InvariantError, match=r"expected turn 2, got 3"):
            second.append("turn/start", {"turn": 3})

        env3 = await setup_env()
        sessions3: SessionStore = env3["ctx"].get("sessions")
        third = sessions3.create()
        third.append("turn/start", {"turn": 1})
        third.append("step/start", {"turn": 1, "step": 1})
        third.append("step/end", {"turn": 1, "step": 1})
        third.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

        env4 = await setup_env()
        sessions4: SessionStore = env4["ctx"].get("sessions")
        enclosed = sessions4.create()
        enclosed.append("turn/start", {"turn": 1})
        enclosed.append("step/start", {"turn": 1, "step": 1})
        enclosed.append("request/header", {
            "header": {"config": {"provider": "mock", "model": "mock"}},
            "reason": "initial",
        })
        enclosed.append("request/context", {"provider": "mock", "model": "mock"})

        env5 = await setup_env()
        sessions5: SessionStore = env5["ctx"].get("sessions")
        outside = sessions5.create()
        outside.append(
            "user/message",
            create_user_message({
                "content": [{"type": "text", "text": "idle context"}],
                "source": {"kind": "plugin", "plugin": "test"},
            }),
            surface_op="append",
        )
        with pytest.raises(InvariantError, match=r"outside any open turn"):
            outside.append("request/context", {"provider": "mock", "model": "m", "contextWindow": 128000})

    @pytest.mark.asyncio
    async def test_enforces_open_step_identity_and_numbering(self):
        env = await setup_env()
        sessions: SessionStore = env["ctx"].get("sessions")
        wrong_turn = sessions.create()
        wrong_turn.append("turn/start", {"turn": 1})
        with pytest.raises(InvariantError, match=r"open turn is 1"):
            wrong_turn.append("step/start", {"turn": 2, "step": 1})

        nested = sessions.create()
        nested.append("turn/start", {"turn": 1})
        nested.append("step/start", {"turn": 1, "step": 1})
        with pytest.raises(InvariantError, match=r"while step 1 is still open"):
            nested.append("step/start", {"turn": 1, "step": 2})
        with pytest.raises(InvariantError, match=r"while step 1 is still open"):
            nested.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
        with pytest.raises(InvariantError, match=r"open is turn 1/step 1"):
            nested.append("step/end", {"turn": 1, "step": 2})

        skipped = sessions.create()
        skipped.append("turn/start", {"turn": 1})
        skipped.append("step/start", {"turn": 1, "step": 1})
        skipped.append("step/end", {"turn": 1, "step": 1})
        with pytest.raises(InvariantError, match=r"expected step 2 in turn 1, got 3"):
            skipped.append("step/start", {"turn": 1, "step": 3})

    @pytest.mark.asyncio
    async def test_requires_step_scoped_stream_and_tool_events_to_name_open_step(self):
        env = await setup_env()
        sessions: SessionStore = env["ctx"].get("sessions")
        chunk = sessions.create()
        chunk.append("turn/start", {"turn": 1})
        with pytest.raises(InvariantError, match=r"open is turn 1/step null"):
            chunk.append("assistant/chunk", {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "x"}})

        tool = sessions.create()
        tool.append("turn/start", {"turn": 1})
        tool.append("step/start", {"turn": 1, "step": 1})
        with pytest.raises(InvariantError, match=r"no prior tool/call"):
            tool.append(
                "tool/result",
                {
                    "turn": 1,
                    "step": 1,
                    "message": create_tool_result_message({
                        "callId": "ghost",
                        "content": [],
                        "isError": False,
                    }),
                },
                surface_op="append",
            )

    @pytest.mark.asyncio
    async def test_treats_validated_tool_result_replacement_as_turn_enclosed_rewrite(self):
        env = await setup_env()
        sessions: SessionStore = env["ctx"].get("sessions")
        session = sessions.create()
        session.append("turn/start", {"turn": 1})
        session.append("step/start", {"turn": 1, "step": 1})
        session.append("tool/call", {"turn": 1, "step": 1, "callId": "rewrite", "name": "echo", "arguments": "{}"})
        original = session.append(
            "tool/result",
            {
                "turn": 1,
                "step": 1,
                "message": create_tool_result_message({
                    "callId": "rewrite",
                    "content": [{"type": "text", "text": "original"}],
                    "isError": False,
                }),
            },
            surface_op="append",
        )
        session.append("step/end", {"turn": 1, "step": 1})
        session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

        session.append("turn/start", {"turn": 2})
        data_copy = dict(original["data"])
        msg_copy = dict(data_copy["message"])
        item_copy = dict(msg_copy["content"][0])
        item_copy["content"] = [{"type": "text", "text": "pruned"}]
        msg_copy["content"] = [item_copy]
        data_copy["message"] = freeze_message(msg_copy)

        session.append(
            "tool/result",
            data_copy,
            surface_op={"op": "replace", "start": original["seq"], "end": original["seq"]},
            source_event_seqs=[original["seq"]],
        )

    @pytest.mark.asyncio
    async def test_rejects_tool_result_replacement_outside_a_turn(self):
        env = await setup_env()
        sessions: SessionStore = env["ctx"].get("sessions")
        session = sessions.create()
        session.append("turn/start", {"turn": 1})
        session.append("step/start", {"turn": 1, "step": 1})
        session.append("tool/call", {"turn": 1, "step": 1, "callId": "rewrite", "name": "echo", "arguments": "{}"})
        original = session.append(
            "tool/result",
            {
                "turn": 1,
                "step": 1,
                "message": create_tool_result_message({
                    "callId": "rewrite",
                    "content": [{"type": "text", "text": "original"}],
                    "isError": False,
                }),
            },
            surface_op="append",
        )
        session.append("step/end", {"turn": 1, "step": 1})
        session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

        data_copy = dict(original["data"])
        msg_copy = dict(data_copy["message"])
        item_copy = dict(msg_copy["content"][0])
        item_copy["content"] = [{"type": "text", "text": "pruned"}]
        msg_copy["content"] = [item_copy]
        data_copy["message"] = freeze_message(msg_copy)

        with pytest.raises(InvariantError, match=r"outside any open turn"):
            session.append(
                "tool/result",
                data_copy,
                surface_op={"op": "replace", "start": original["seq"], "end": original["seq"]},
                source_event_seqs=[original["seq"]],
            )

    @pytest.mark.asyncio
    async def test_allows_not_started_repair_results_and_unresolved_calls_at_step_end(self):
        env = await setup_env()
        sessions: SessionStore = env["ctx"].get("sessions")
        repaired = sessions.create()
        repaired.append("turn/start", {"turn": 1})
        repaired.append("step/start", {"turn": 1, "step": 1})
        repaired.append(
            "tool/result",
            {
                "turn": 1,
                "step": 1,
                "message": create_tool_result_message({
                    "callId": "crashed",
                    "content": [],
                    "isError": True,
                }),
                "error": {"name": "ToolNotStartedError", "code": TOOL_NOT_STARTED},
            },
            surface_op="append",
        )
        repaired.append("step/end", {"turn": 1, "step": 1})
        repaired.append("turn/end", {"turn": 1, "reason": {"kind": "interrupted"}})

        unresolved = sessions.create()
        unresolved.append("turn/start", {"turn": 1})
        unresolved.append("step/start", {"turn": 1, "step": 1})
        unresolved.append("tool/call", {"turn": 1, "step": 1, "callId": "c1", "name": "echo", "arguments": "{}"})
        unresolved.append("step/end", {"turn": 1, "step": 1})
        unresolved.append("turn/end", {"turn": 1, "reason": {"kind": "error", "error": {"message": "boom", "code": "UNKNOWN"}}})

    @pytest.mark.asyncio
    async def test_does_not_let_result_in_later_step_satisfy_earlier_call(self):
        env = await setup_env()
        sessions: SessionStore = env["ctx"].get("sessions")
        session = sessions.create()
        session.append("turn/start", {"turn": 1})
        session.append("step/start", {"turn": 1, "step": 1})
        session.append("tool/call", {"turn": 1, "step": 1, "callId": "c1", "name": "echo", "arguments": "{}"})
        session.append("step/end", {"turn": 1, "step": 1})
        session.append("step/start", {"turn": 1, "step": 2})
        with pytest.raises(InvariantError, match=r"no prior tool/call in this step"):
            session.append(
                "tool/result",
                {
                    "turn": 1,
                    "step": 2,
                    "message": create_tool_result_message({
                        "callId": "c1",
                        "content": [],
                        "isError": False,
                    }),
                },
                surface_op="append",
            )


    @pytest.mark.asyncio
    async def test_does_not_advance_committed_trace_state_when_a_later_dispatch_listener_vetoes(self):
        env = await setup_env()
        ctx: Context = env["ctx"]
        sessions: SessionStore = ctx.get("sessions")
        session = sessions.create(SessionId("dispatch-veto-rollback"))
        state = {"veto": True}

        def on_dispatch(mode, name, args, *extra):
            if name != "session/event" or not state["veto"]:
                return
            state["veto"] = False
            raise ValueError("later dispatch veto")

        ctx.on("internal/dispatch", on_dispatch)

        with pytest.raises(ValueError, match="later dispatch veto"):
            session.append("turn/start", {"turn": 1})
        assert session.events == []
        # The committed trace did not advance, so the retried sequence is legal.
        session.append("turn/start", {"turn": 1})
        session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

    @pytest.mark.asyncio
    async def test_rejects_non_monotonic_event_sequence_numbers(self):
        env = await setup_env()
        ctx: Context = env["ctx"]
        sessions: SessionStore = ctx.get("sessions")
        session = sessions.create()

        ctx.emit(scope_target(session, None), "session/event", session, {
            "type": "turn/start",
            "seq": 0,
            "time": 1,
            "data": {"turn": 1},
        })
        with pytest.raises(InvariantError, match="seq must strictly increase"):
            ctx.emit(scope_target(session, None), "session/event", session, {
                "type": "turn/end",
                "seq": 0,
                "time": 2,
                "data": {"turn": 1, "reason": {"kind": "completed"}},
            })

    @pytest.mark.asyncio
    async def test_keeps_fresh_tool_result_appends_open_step_checked(self):
        env = await setup_env()
        ctx: Context = env["ctx"]
        sessions: SessionStore = ctx.get("sessions")
        session = sessions.create()
        session.append("turn/start", {"turn": 1})

        with pytest.raises(InvariantError, match=r"open is turn 1/step null"):
            session.append(
                "tool/result",
                {
                    "turn": 1,
                    "step": 1,
                    "message": create_tool_result_message({
                        "callId": "closed",
                        "content": [],
                        "isError": False,
                    }),
                },
                surface_op="append",
            )

    @pytest.mark.asyncio
    async def test_replays_seeded_sessions_and_tracks_each_session_independently(self):
        env = await setup_env()
        ctx: Context = env["ctx"]
        sessions: SessionStore = ctx.get("sessions")
        bad_seed = [
            {"type": "turn/start", "seq": 0, "time": 0, "data": {"turn": 1}},
            {"type": "turn/start", "seq": 1, "time": 0, "data": {"turn": 2}},
        ]
        with pytest.raises(InvariantError):
            sessions.create(None, {"seed": bad_seed})

        a = sessions.create(SessionId("a"))
        b = sessions.create(SessionId("b"))
        a.append("turn/start", {"turn": 1})
        b.append("turn/start", {"turn": 1})

    @pytest.mark.asyncio
    async def test_rebuilds_trace_state_for_sessions_that_exist_when_the_companion_reloads(self):
        ctx = Context()
        SessionPlugin().apply(ctx)
        InvariantRegistry(ctx)
        fiber = ctx.plugin(SessionInvariantPlugin)

        sessions: SessionStore = ctx.get("sessions")
        session = sessions.create()
        session.append("turn/start", {"turn": 1})
        session.append("step/start", {"turn": 1, "step": 1})

        await fiber.dispose()
        ctx.plugin(SessionInvariantPlugin)

        # The reloaded companion re-seeded the live session from its log.
        session.append("assistant/chunk", {
            "turn": 1,
            "step": 1,
            "chunk": {"type": "text-delta", "index": 0, "text": "h"},
        })
        with pytest.raises(InvariantError, match="turn 1 is still open"):
            session.append("turn/start", {"turn": 2})

    @pytest.mark.asyncio
    async def test_accepts_end_seed_whether_or_not_a_turn_is_open(self):
        env = await setup_env()
        ctx: Context = env["ctx"]
        sessions: SessionStore = ctx.get("sessions")

        # Balanced seed: between turns.
        sessions.create(SessionId("inherited-between-turns"), {"seed": [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
            {"type": "turn/end", "seq": 1, "time": 2, "data": {"turn": 1, "reason": {"kind": "completed"}}},
        ]})

        # Unbalanced seed: inside the open turn, which the relation permits.
        open_session = sessions.create(SessionId("inherited-inside-open-turn"), {"seed": [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
        ]})
        assert [event["type"] for event in open_session.events] == ["turn/start", "session/end-seed"]
        # Still open afterwards: the boundary moves no cursor.
        with pytest.raises(InvariantError, match="turn 1 is still open"):
            open_session.append("turn/start", {"turn": 2})
        open_session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

    @pytest.mark.asyncio
    async def test_removes_all_listeners_when_the_companion_is_disposed(self):
        ctx = Context()
        SessionPlugin().apply(ctx)
        InvariantRegistry(ctx)
        fiber = ctx.plugin(SessionInvariantPlugin)

        sessions: SessionStore = ctx.get("sessions")
        session = sessions.create()
        session.append("turn/start", {"turn": 1})

        await fiber.dispose()
        session.append("turn/start", {"turn": 2})
