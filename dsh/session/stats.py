"""
Session Stats Projection (`@deepseek-ai/dsh-session-stats`).
Provides whole-log conversation figures (turn count, step count, LLM ms, Tool ms, token counts).
"""

from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.session.projections import ProjectionDefinition, SessionProjectionRegistry


class SessionStatsProjection:
    """Accumulated whole-log stats."""

    def __init__(
        self,
        turns: int = 0,
        steps: int = 0,
        llm_ms: int = 0,
        tool_ms: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        reasoning_tokens: int = 0,
    ):
        self.turns = turns
        self.steps = steps
        self.llm_ms = llm_ms
        self.tool_ms = tool_ms
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.reasoning_tokens = reasoning_tokens

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turns": self.turns,
            "steps": self.steps,
            "llmMs": self.llm_ms,
            "toolMs": self.tool_ms,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "reasoningTokens": self.reasoning_tokens,
        }


def init_session_stats() -> Dict[str, Any]:
    return {
        "turns": 0,
        "steps": 0,
        "llmMs": 0,
        "toolMs": 0,
        "promptTokens": 0,
        "completionTokens": 0,
        "reasoningTokens": 0,
        "_open_steps": {},  # (turn, step) -> start_time
        "_open_calls": {},  # call_id -> start_time
        "_counted_turns": set(),
    }


def apply_session_stats(state: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    state = dict(state)
    etype = event.get("type")
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    etime = event.get("time", 0)

    if etype == "step/start":
        turn = data.get("turn", 0)
        step = data.get("step", 0)
        state["_open_steps"] = dict(state["_open_steps"])
        state["_open_steps"][(turn, step)] = etime
    elif etype == "step/end":
        turn = data.get("turn", 0)
        step = data.get("step", 0)
        state["steps"] += 1
        counted = set(state["_counted_turns"])
        if turn not in counted:
            counted.add(turn)
            state["_counted_turns"] = counted
            state["turns"] = len(counted)
        open_steps = dict(state["_open_steps"])
        start_t = open_steps.pop((turn, step), None)
        state["_open_steps"] = open_steps
        if start_t and etime >= start_t:
            state["llmMs"] += (etime - start_t)
    elif etype == "assistant/message":
        usage = data.get("usage", {})
        if isinstance(usage, dict):
            state["promptTokens"] += usage.get("prompt_tokens") or usage.get("promptTokens") or 0
            state["completionTokens"] += usage.get("completion_tokens") or usage.get("completionTokens") or 0
            state["reasoningTokens"] += usage.get("reasoning_tokens") or usage.get("reasoningTokens") or 0
    elif etype == "tool/call":
        cid = data.get("callId") or data.get("call_id")
        if cid:
            open_calls = dict(state["_open_calls"])
            open_calls[cid] = etime
            state["_open_calls"] = open_calls
    elif etype == "tool/result":
        cid = data.get("tool_call_id") or data.get("callId")
        open_calls = dict(state["_open_calls"])
        start_t = open_calls.pop(cid, None) if cid else None
        state["_open_calls"] = open_calls
        if start_t and etime >= start_t:
            state["toolMs"] += (etime - start_t)

    return state


def view_session_stats(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "turns": state["turns"],
        "steps": state["steps"],
        "llmMs": state["llmMs"],
        "toolMs": state["toolMs"],
        "promptTokens": state["promptTokens"],
        "completionTokens": state["completionTokens"],
        "reasoningTokens": state["reasoningTokens"],
    }


class SessionStatsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-stats`: Registers sessionStats projection.
    """

    id = "session-stats"
    name = "@deepseek-ai/dsh-session-stats"

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
