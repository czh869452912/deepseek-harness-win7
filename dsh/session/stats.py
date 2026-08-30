"""
Session Stats Projection (`@deepseek-ai/dsh-session-stats`).
Provides whole-log conversation figures (turn count, step count, LLM ms, Tool ms, TTFT ms, decode ms, decode tokens).
1:1 aligned with official `@deepseek-ai/dsh-session-stats`.
"""

from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.session.projections import ProjectionDefinition, SessionProjectionRegistry


class SessionStatsProjection:
    """Session stats container for typed access."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def is_token_delta(chunk: Any) -> bool:
    """Whether a stream chunk carries a non-empty first-token delta."""
    if not isinstance(chunk, dict):
        return False
    ctype = chunk.get("type")
    if ctype in ("text-delta", "reasoning-delta"):
        return bool(chunk.get("text", ""))
    if ctype == "tool-call-delta":
        return bool(chunk.get("argumentsDelta", "")) or (chunk.get("name") is not None)
    return False


def usage_output_tokens(usage: Any) -> Optional[int]:
    """Provider-reported completion tokens."""
    if not isinstance(usage, dict):
        return None
    val = usage.get("outputTokens")
    if val is None:
        val = usage.get("output_tokens")
    if val is None:
        val = usage.get("completion_tokens")
    if val is None:
        val = usage.get("completionTokens")
    if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
        return int(val)
    return None


def init_session_stats() -> Dict[str, Any]:
    return {
        "turns": 0,
        "steps": 0,
        "llmMs": 0,
        "toolMs": 0,
        "ttftMs": 0,
        "ttftSteps": 0,
        "decodeMs": 0,
        "decodeTokens": 0,
        "lastTurn": None,
        "openStep": None,
        "pendingCalls": {},
    }


def apply_session_stats(state: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    etype = event.get("type")
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    etime = event.get("time", 0)

    if etype == "step/start":
        return {
            **state,
            "openStep": {
                "turn": data.get("turn", 0),
                "step": data.get("step", 0),
                "startTime": etime,
                "firstTokenTime": None,
            },
        }

    if etype == "assistant/chunk":
        open_s = state.get("openStep")
        if open_s is None or open_s.get("turn") != data.get("turn") or open_s.get("step") != data.get("step"):
            return state
        if open_s.get("firstTokenTime") is not None or not is_token_delta(data.get("chunk")):
            return state
        new_open = dict(open_s)
        new_open["firstTokenTime"] = etime
        return {**state, "openStep": new_open}

    if etype == "assistant/message":
        open_s = state.get("openStep")
        if open_s is None or open_s.get("turn") != data.get("turn") or open_s.get("step") != data.get("step"):
            return state
        next_state = dict(state)
        start_t = open_s.get("startTime", etime)
        next_state["llmMs"] = state["llmMs"] + max(0, etime - start_t)
        next_state["openStep"] = None

        first_token_t = open_s.get("firstTokenTime")
        if first_token_t is not None:
            next_state["ttftMs"] = state["ttftMs"] + max(0, first_token_t - start_t)
            next_state["ttftSteps"] = state["ttftSteps"] + 1
            out_tokens = usage_output_tokens(data.get("usage"))
            if out_tokens is not None:
                next_state["decodeMs"] = state["decodeMs"] + max(0, etime - first_token_t)
                next_state["decodeTokens"] = state["decodeTokens"] + out_tokens
        return next_state

    if etype == "tool/call":
        cid = data.get("callId") or data.get("call_id")
        if cid:
            new_calls = dict(state.get("pendingCalls", {}))
            new_calls[str(cid)] = etime
            return {**state, "pendingCalls": new_calls}
        return state

    if etype == "tool/result":
        msg = data.get("message", {}) if isinstance(data.get("message"), dict) else {}
        src = msg.get("source", {}) if isinstance(msg.get("source"), dict) else {}
        cid = src.get("callId") or src.get("call_id") or data.get("tool_call_id") or data.get("callId")
        if not cid:
            return state
        cid_str = str(cid)
        pending = state.get("pendingCalls", {})
        if cid_str not in pending:
            return state
        dispatched = pending[cid_str]
        new_pending = {k: v for k, v in pending.items() if k != cid_str}
        return {
            **state,
            "toolMs": state["toolMs"] + max(0, etime - dispatched),
            "pendingCalls": new_pending,
        }

    if etype == "step/end":
        turn = data.get("turn", 0)
        last_turn = state.get("lastTurn")
        new_turns = state["turns"] if last_turn == turn else state["turns"] + 1
        return {
            **state,
            "turns": new_turns,
            "steps": state["steps"] + 1,
            "lastTurn": turn,
            "openStep": None,
        }

    if etype == "turn/end":
        if not state.get("pendingCalls"):
            return state
        return {**state, "pendingCalls": {}}

    return state


def view_session_stats(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "turns": state["turns"],
        "steps": state["steps"],
        "llmMs": state["llmMs"],
        "toolMs": state["toolMs"],
        "ttftMs": state["ttftMs"],
        "ttftSteps": state["ttftSteps"],
        "decodeMs": state["decodeMs"],
        "decodeTokens": state["decodeTokens"],
    }


sessionStatsProjectionDefinition = ProjectionDefinition(
    key="sessionStats",
    schema=None,
    init=init_session_stats,
    apply=apply_session_stats,
    view=view_session_stats,
    state_version=1,
)


class SessionStatsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-stats`: Registers sessionStats projection.
    """

    id = "session-stats"
    name = "@deepseek-ai/dsh-session-stats"
    inject = ["sessionProjections"]

    def apply(self, ctx: Any) -> None:
        projections: Optional[SessionProjectionRegistry] = ctx.get("sessionProjections")
        if projections:
            projections.register(
                key="sessionStats",
                schema=None,
                init=init_session_stats,
                apply=apply_session_stats,
                view=view_session_stats,
            )

