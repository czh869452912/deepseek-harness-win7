from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions
from dsh.core.session import Session
from dsh.subagent.descriptor import snapshot_descriptor, fold_descriptor, completed_turn_prefix, final_assistant_output
from dsh.subagent.composition import child_depth, child_options, child_meta, capture_policy, append_policy


def test_descriptor_first_record_is_authoritative_and_only_declared_composition_persists():
    source = {"mode": "continuable", "provider": "fork", "label": "analysis", "agentProvider": "deepseek",
              "maxTokens": 5, "outputSchema": object(), "toolFilter": {"allow": ["read"]}}
    value = snapshot_descriptor(source)
    assert value == {"version": 3, "mode": "continuable", "provider": "fork", "label": "analysis",
                     "agentProvider": "deepseek", "toolFilter": {"allow": ["read"]}}
    source["toolFilter"]["allow"].append("write")
    assert value["toolFilter"]["allow"] == ["read"]
    events = [{"type": "subagent/descriptor", "data": value}, {"type": "subagent/descriptor", "data": {"version": 100}}]
    assert fold_descriptor(events) == value
    assert fold_descriptor(list(reversed(events))) is None
    events[0]["data"]["unexpected"] = True
    with pytest.raises(ValueError, match="unknown"):
        fold_descriptor(events)


def test_parent_depth_floor_and_request_time_route_selection():
    parent = Agent(Session.create("parent", header={"version": 0, "id": "parent", "createdAt": 1, "delegationDepth": 2, "cwd": "C:/workspace"}),
                   AgentOptions(provider="old", model="old", reasoningEffort="high", maxTokens=100))
    parent.options.subagentDepth = 0
    parent.session.append_request_header({"config": {"provider": "new", "model": "selected", "reasoningEffort": "low"}})
    assert child_depth(parent, 3) == 3
    with pytest.raises(ValueError, match="exceeds"):
        child_depth(parent, 2)
    inherited = child_options(parent, None, 3)
    assert inherited.provider == "new" and inherited.reasoningEffort == "low" and inherited.maxTokens == 100
    changed = child_options(parent, {"model": "other"}, 3)
    assert changed.reasoningEffort is None and changed.subagentDepth == 3
    meta = child_meta(parent, 3, 10)
    assert meta == {"parentSession": "parent", "origin": "subagent", "delegationDepth": 3, "cwd": "C:/workspace", "seedLength": 10}
    for invalid in (-0.0, True, -1, 1.5, 9007199254740992):
        parent.options.subagentDepth = invalid
        with pytest.raises(ValueError):
            child_depth(parent)


def test_fork_prefix_excludes_open_turn_and_empty_final_message_preserves_output():
    session = Session.create("parent")
    session.append("turn/start", {"turn": 1})
    session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
    session.append("turn/start", {"turn": 2})
    assert len(completed_turn_prefix(SimpleNamespace(session=session))) == 2
    events = [
        {"type": "assistant/chunk", "data": {"chunk": {"type": "text-delta", "text": "partial"}}},
        {"type": "assistant/message", "data": {"message": {"content": [{"type": "text", "text": "answer"}]}}},
        {"type": "assistant/message", "data": {"message": {"content": []}}}]
    assert final_assistant_output(events) == [{"type": "text", "text": "answer"}]
    assert final_assistant_output(events[:1]) == [{"type": "text", "text": "partial"}]


def test_delegation_policy_captures_explicit_sandbox_and_pins_approval():
    ctx = Context()
    ctx.set_service("sandboxPolicy", SimpleNamespace(override_of=lambda session: "read-only"))
    ctx.set_service("approval", object())
    parent = Agent(Session.create("parent"), ctx=ctx)
    policy = capture_policy(parent)
    child = Session.create("child")
    append_policy(child, policy)
    assert [event["data"] for event in child.events] == [
        {"mode": "read-only", "source": "delegation"}, {"policy": "never", "source": "delegation"}]
