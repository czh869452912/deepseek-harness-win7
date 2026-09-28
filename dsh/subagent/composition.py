"""Shared child route, durable lineage, delegated policy and scoped composition."""
import math

from dsh.core.agent import AgentOptions
from dsh.core.system_prompt import PERSONA_ORDER

MAX_SAFE = 9007199254740991
DELEGATION_CONTEXT = ('You are a delegated subagent: your permission scope was fixed when you were started and cannot be '
    'widened from inside this session — operations that require approval are rejected automatically. '
    'When the task needs access beyond that scope, do not retry the denied operation; state the '
    'limitation in your reply so the delegating agent can handle it.')


def valid_depth(value):
    if (type(value) not in (int, float) or not 0 <= value <= MAX_SAFE or int(value) != value
            or value == 0 and math.copysign(1, value) < 0):
        raise ValueError("subagent depth must be a non-negative safe integer")
    return int(value)


def delegation_depth(parent):
    options = parent.options
    runtime = options.get("subagentDepth", 0) if isinstance(options, dict) else getattr(options, "subagentDepth", 0)
    return max(parent.session.header.delegationDepth or 0, valid_depth(runtime))


def child_depth(parent, maximum=None):
    if maximum is not None:
        valid_depth(maximum)
    depth = valid_depth(delegation_depth(parent) + 1)
    if maximum is not None and depth > maximum:
        error = ValueError("subagent depth {} exceeds maxDepth {}".format(depth, maximum))
        error.attemptedDepth, error.maxDepth = depth, maximum
        raise error
    return depth


def parent_options(parent):
    options = dict(parent.options) if isinstance(parent.options, dict) else parent.options.to_dict()
    header = parent.session.requestHeader()
    if header and "config" in header:
        for key in ("provider", "model", "reasoningEffort"):
            options.pop(key, None)
            if key in header["config"]:
                options[key] = header["config"][key]
    return options


def child_options(parent, requested, depth):
    inherited = parent_options(parent)
    result = {key: inherited[key] for key in ("provider", "model", "reasoningEffort", "maxTokens") if key in inherited}
    result.update(requested or {})
    result["subagentDepth"] = depth
    if any(result.get(key) != inherited.get(key) for key in ("provider", "model")) and "reasoningEffort" not in (requested or {}):
        result.pop("reasoningEffort", None)
    options = AgentOptions(provider=result.get("provider"), model=result.get("model"),
                           reasoningEffort=result.get("reasoningEffort"), maxTokens=result.get("maxTokens"))
    options.subagentDepth = depth
    return options


def child_meta(parent, depth, seed_length):
    header = parent.session.header
    result = {"parentSession": header.id, "origin": "subagent", "delegationDepth": depth}
    if header.cwd is not None:
        result["cwd"] = header.cwd
    presets = parent.ctx.get("agentPresets")
    if presets is not None:
        preset = presets.composedPreset(parent.ctx)
        if preset is not None:
            result["agentPreset"] = preset
    if seed_length > 0:
        result["seedLength"] = seed_length
    return result


def capture_policy(parent):
    result = {}
    policy = parent.ctx.get("sandboxPolicy")
    if policy is not None:
        mode = policy.override_of(parent.session)
        if mode is not None:
            result["sandboxMode"] = mode
    if parent.ctx.get("approval") is not None:
        result["approvalPolicy"] = "never"
    return result


def append_policy(session, policy):
    if "sandboxMode" in policy:
        session.append("sandbox/mode", {"mode": policy["sandboxMode"], "source": "delegation"})
    if "approvalPolicy" in policy:
        session.append("approval/policy", {"policy": policy["approvalPolicy"], "source": "delegation"})


def apply_composition(child_ctx, parent, composition):
    presets = child_ctx.get("agentPresets")
    if presets is not None:
        presets.composeFrom(child_ctx, parent.ctx)
    child_ctx.get("systemPrompt").context({"name": "subagent:delegation", "order": 120, "text": DELEGATION_CONTEXT})
    if "persona" in composition:
        child_ctx.get("systemPrompt").section({"name": "deployment:persona", "order": PERSONA_ORDER, "text": composition["persona"]})
    if "toolFilter" in composition:
        child_ctx.get("tools").restrict(composition["toolFilter"])
