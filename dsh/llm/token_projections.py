"""Bounded, executable token-meter projection definitions and cache schemas."""
import math

from dsh.core.session import canonical_header, derive_event_message
from dsh.core.surface import is_surface_event
from dsh.llm.token_estimate import estimate_message, estimate_system_tokens, estimate_tools_tokens

BUCKETS = ("uncachedInputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens")


def _object(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError("invalid token projection object")
    return value


def _count(value, positive=False):
    try:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and value == int(value) and value >= (1 if positive else 0))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("expected non-negative integral token count")


def _counts(value, required, optional=()):
    _object(value, required, optional)
    for key, count in value.items():
        _count(count, key == "contextWindow")
    return value


def _claim(value):
    return _counts(value, ("start", "end", "tokens"))


def usage_state(value):
    _object(value, ("totals", "last"))
    _counts(value["totals"], BUCKETS)
    if value["last"] is not None:
        last = _object(value["last"], ("turn", "step", "buckets"))
        _count(last["turn"])
        _count(last["step"])
        _counts(last["buckets"], BUCKETS)
    return value


def pressure_state(value):
    _object(value, ("surfaceTokens",), ("contextWindow", "pressureTokens", "sampledSurfaceTokens", "claim"))
    for key, count in value.items():
        _claim(count) if key == "claim" else _count(count, key == "contextWindow")
    return value


def breakdown_state(value):
    _object(value, ("systemTokens", "toolsTokens", "messageTokens"), ("claim",))
    for key, count in value.items():
        _claim(count) if key == "claim" else _count(count)
    return value


def fold_surface(claim, event):
    kind, data = event["type"], event["data"]
    if kind in ("compaction/summary", "compaction/prune"):
        return 0, dict(data["shadowedRange"], tokens=data["shadowedTokenCount"])
    if not is_surface_event(event):
        return 0, None
    message = derive_event_message(event)
    tokens = 0 if message is None else estimate_message(message)
    op = event["surfaceOp"]
    if op == "append":
        return tokens, None
    if claim is None:
        return 0, None
    if (claim["start"], claim["end"]) != (op["start"], op["end"]):
        raise ValueError("token surface: replace at seq {} over range {}-{} has no adjacent shadow price (armed claim covers {}-{})".format(
            event["seq"], op["start"], op["end"], claim["start"], claim["end"]))
    return tokens - claim["tokens"], None


def usage_of(event):
    kind, data = event["type"], event["data"]
    if kind == "assistant/chunk" and data["chunk"]["type"] == "usage":
        return data["chunk"]["usage"]
    if kind == "assistant/message":
        return data.get("usage")
    return None


def fold_usage(state, event):
    data, last = event["data"], state["last"]
    if event["type"] == "llm/retry-started":
        if last is not None and (last["turn"], last["step"]) == (data["turn"], data["step"]):
            return dict(state, last=None)
        return state
    usage = usage_of(event)
    if usage is None:
        return state
    buckets = dict(zip(BUCKETS, (usage["inputTokens"], usage["outputTokens"],
                                usage.get("cacheReadTokens", 0), usage.get("cacheWriteTokens", 0))))
    previous = last["buckets"] if last is not None and (last["turn"], last["step"]) == (data["turn"], data["step"]) else {}
    if previous == buckets:
        return state
    return dict(totals={key: state["totals"][key] - previous.get(key, 0) + buckets[key] for key in BUCKETS},
                last=dict(turn=data["turn"], step=data["step"], buckets=buckets))


def fold_pressure(state, event):
    delta, claim = fold_surface(state.get("claim"), event)
    next_state = state
    if event["type"] == "request/context":
        window = event["data"].get("contextWindow")
        if window != state.get("contextWindow"):
            next_state = dict(next_state)
            next_state.pop("contextWindow", None)
            if window is not None:
                next_state["contextWindow"] = window
    usage = usage_of(event)
    if usage is not None:
        pressure = sum(usage.get(key, 0) for key in ("inputTokens", "cacheReadTokens", "cacheWriteTokens"))
        if pressure != next_state.get("pressureTokens") or next_state.get("sampledSurfaceTokens") != next_state["surfaceTokens"]:
            next_state = dict(next_state, pressureTokens=pressure, sampledSurfaceTokens=next_state["surfaceTokens"])
    if delta:
        next_state = dict(next_state, surfaceTokens=next_state["surfaceTokens"] + delta)
    if state.get("claim") is None and claim is None:
        return next_state
    next_state = dict(next_state)
    next_state.pop("claim", None)
    if claim is not None:
        next_state["claim"] = claim
    return next_state


def pressure_view(state):
    view = {key: state[key] for key in ("contextWindow", "pressureTokens") if key in state}
    if "pressureTokens" in state and "sampledSurfaceTokens" in state:
        view["projectedTokens"] = max(0, state["pressureTokens"] + state["surfaceTokens"] - state["sampledSurfaceTokens"])
    return view


def fold_breakdown(state, event):
    delta, claim = fold_surface(state.get("claim"), event)
    system, tools = state["systemTokens"], state["toolsTokens"]
    if event["type"] == "request/header":
        header = canonical_header(event["data"]["header"])
        system, tools = estimate_system_tokens(header), estimate_tools_tokens(header)
    if (system == state["systemTokens"] and tools == state["toolsTokens"]
            and not delta and claim is None and state.get("claim") is None):
        return state
    result = dict(systemTokens=system, toolsTokens=tools, messageTokens=state["messageTokens"] + delta)
    if claim is not None:
        result["claim"] = claim
    return result


TOKEN_USAGE = dict(key="tokenUsage", stateVersion=2, stateSchema=usage_state,
                   init=lambda _: dict(totals=dict.fromkeys(BUCKETS, 0), last=None), apply=fold_usage,
                   wire=dict(viewSchema=lambda value: _counts(value, BUCKETS), view=lambda state: state["totals"]))
CONTEXT_PRESSURE = dict(key="contextPressure", stateVersion=4, stateSchema=pressure_state,
                        init=lambda _: dict(surfaceTokens=0), apply=fold_pressure,
                        wire=dict(viewSchema=lambda value: _counts(value, (), ("contextWindow", "pressureTokens", "projectedTokens")), view=pressure_view))
CONTEXT_BREAKDOWN = dict(key="contextBreakdown", stateVersion=2, stateSchema=breakdown_state,
                         init=lambda _: dict(systemTokens=0, toolsTokens=0, messageTokens=0), apply=fold_breakdown,
                         wire=dict(viewSchema=lambda value: _counts(value, ("systemTokens", "toolsTokens", "messageTokens")),
                                   view=lambda state: {key: state[key] for key in ("systemTokens", "toolsTokens", "messageTokens")}))
DEFINITIONS = (TOKEN_USAGE, CONTEXT_PRESSURE, CONTEXT_BREAKDOWN)
