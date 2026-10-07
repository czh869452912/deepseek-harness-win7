from dsh.core.agent import AgentPlugin
from dsh.core.system_prompt import SystemPrompt as SourceToolsPrompt
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.agent import Agent
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import Session, SessionPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.guard.repeat_tool_reminder import (
    RepeatToolReminderPlugin, GENTLE_REMINDER, canonicalize, preview_arguments,
)


@pytest.mark.parametrize("args, expected", [
    ({"q": 1.0}, '{"q":1}'),
    ({"q": -0.0}, '{"q":0}'),
    ({"q": 0.00001}, '{"q":0.00001}'),
    ({"q": 1e21}, '{"q":1e+21}'),
    ({"q": 9007199254740993}, '{"q":9007199254740992}'),
    ({"q": float("inf")}, '{"q":null}'),
    ({"q": "\ud83d\ude00\ud800"}, '{"q":"\U0001f600\\ud800"}'),
    ({"z": [{"b": False, "a": None}], "a": "x"}, '{"a":"x","z":[{"a":null,"b":false}]}'),
    ({"10": "a", "2": "b", "01": "c"}, '{"2":"b","10":"a","01":"c"}'),
    ({"\ue000": 2, "\U00010000": 1}, '{"\U00010000":1,"\ue000":2}'),
    ("{bad json", '"{bad json"'),
    ({"__proto__": {"q": 1}, "ok": True}, '{"__proto__":{"q":1},"ok":true}'),
])
def test_canonical_parsed_json(args, expected):
    before = copy.deepcopy(args)
    assert canonicalize(args) == expected
    assert args == before


def test_reminder_normalizes_number_and_string_representations():
    plugin = RepeatToolReminderPlugin(dict(thresholds=[2]))
    assert plugin.record_and_check("same", "probe", dict(q=1)) is None
    assert plugin.record_and_check("same", "probe", dict(q=1.0)) == GENTLE_REMINDER
    assert plugin.record_and_check("unicode", "probe", dict(q="\ud83d\ude00")) is None
    assert plugin.record_and_check("unicode", "probe", dict(q="\U0001f600")) == GENTLE_REMINDER


def test_preview_counts_utf16_and_preserves_split_surrogate():
    assert preview_arguments('"\U0001f600x"', 2) == '"\ud83d\u2026 (+3 more chars)'
    assert preview_arguments('"\U0001f600x"', 5) == '"\U0001f600x"'
    assert preview_arguments(canonicalize(dict(body="x" * 400)), 24) == (
        '{"body":"' + "x" * 15 + '\u2026 (+387 more chars)')


def test_distinct_proto_values_do_not_trigger_false_repeat():
    plugin = RepeatToolReminderPlugin(dict(thresholds=[2]))
    assert plugin.record_and_check("proto", "probe", {"__proto__": {"q": 1}}) is None
    assert plugin.record_and_check("proto", "probe", {"__proto__": {"q": 2}}) is None
    assert plugin.record_and_check("proto", "probe", {"__proto__": {"q": 2}}) == GENTLE_REMINDER


@pytest.mark.parametrize("name, expected", [("probe", True), ("probe\n", False),
    ("pro\rbe", False), ("pro\u2028be", False), ("pro\u2029be", False),
    ("mcp.a", True), ("mcpXa", False), ("mcp.b", False)])
def test_wildcard_literal_anchoring_and_line_terminators(name, expected):
    plugin = RepeatToolReminderPlugin(dict(include=["pro*", "mcp.a", "mcp.b"], exclude=["mcp.b"]))
    assert plugin.tracked(name) is expected


@pytest.mark.parametrize("config", [dict(thresholds=[]), dict(thresholds=[1]),
    dict(thresholds=[True]), dict(thresholds=[2.5]), dict(thresholds=[float("inf")]),
    dict(thresholds=[2, 2.0]), dict(thresholds="2"), dict(include="pro*"),
    dict(exclude=[1]), dict(argumentsPreviewChars=0), dict(argumentsPreviewChars=2.5)])
@pytest.mark.asyncio
async def test_config_rejected_on_real_plugin_load(config):
    ctx = Context()
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin)
    try:
        with pytest.raises((ValueError, TypeError)):
            await ctx.plugin(RepeatToolReminderPlugin, config)
    finally:
        await ctx.fiber.dispose()


def test_integral_float_config_and_first_custom_threshold():
    plugin = RepeatToolReminderPlugin(dict(thresholds=[4.0, 2.0], argumentsPreviewChars=10.0))
    assert plugin.thresholds == [2, 4]
    assert plugin.arguments_preview_chars == 10
    outcomes = [plugin.record_and_check("a", "probe", dict(q=1)) for _ in range(4)]
    assert outcomes[1] == GENTLE_REMINDER
    assert "consecutive_calls: 4" in outcomes[3]


@pytest.mark.asyncio
async def test_direct_calls_untracked_transparency_downstream_block_and_unload():
    ctx = Context()
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin)
    fiber = await ctx.plugin(RepeatToolReminderPlugin, dict(thresholds=[2, 3], exclude=["other"]))
    first, fresh = Agent(Session("reused")), Agent(Session("reused"))
    downstream = dict(kind="block", feedback=[dict(type="text", text="sealed")],
                      additionalContexts=None, value="ignored by block", extra="ignored by block")
    async def block(*_args):
        return downstream
    ctx.on("tools/post-execute", block)
    async def attempt(agent, name="probe", args=None):
        return await ctx.waterfall("tools/post-execute", SimpleNamespace(
            agent=agent, name=name, arguments={} if args is None else args), None)
    try:
        assert not ctx.has("repeat_tool_reminder")
        assert await attempt(None) is downstream
        assert await attempt(first) is downstream
        assert await attempt(first, "other") is downstream
        repeated = await attempt(first)
        assert set(repeated) == {"kind", "feedback", "additionalContexts"}
        assert repeated["feedback"] is downstream["feedback"]
        notice = repeated["additionalContexts"][0]
        assert notice["source"] == dict(kind="plugin", plugin="repeat-tool-reminder", form="notice", summary="probe \u00d7 2")
        assert await attempt(fresh) is downstream
        await ctx.waterfall("agent/pre-step", dict(agent=first, messages=[dict(source=dict(kind="tool"))]))
        detailed = await attempt(first)
        assert "consecutive_calls: 3" in detailed["additionalContexts"][0]["content"][0]["text"]
        await ctx.waterfall("agent/pre-step", dict(agent=first, messages=[dict(source=dict(kind="user"))]))
        assert await attempt(first) is downstream
        await fiber.dispose()
        assert await attempt(first) is downstream
        assert downstream["additionalContexts"] is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_downstream_failure_still_advances_chain():
    ctx = Context()
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(RepeatToolReminderPlugin, dict(thresholds=[2]))
    agent = Agent(Session("count"))
    async def fail(*_args):
        raise RuntimeError("downstream failure")
    detach = ctx.on("tools/post-execute", fail)
    data = SimpleNamespace(agent=agent, name="probe", arguments={})
    try:
        with pytest.raises(RuntimeError):
            await ctx.waterfall("tools/post-execute", data, None)
        detach()
        outcome = await ctx.waterfall("tools/post-execute", data, None, lambda *_: dict(kind="accept"))
        assert outcome["additionalContexts"][0]["content"][0]["text"] == GENTLE_REMINDER
    finally:
        await ctx.fiber.dispose()


class ScriptedModel:
    provider, model = "fixture", "fixture"

    def __init__(self, calls):
        self.calls = list(calls)
        self.requests = []

    async def chat_completion_stream(self, messages, tools=None, **_kwargs):
        self.requests.append(copy.deepcopy(messages))
        if not self.calls:
            raise RuntimeError("fixture response budget exhausted")
        call = self.calls.pop(0)
        if call is None:
            yield dict(choices=[dict(delta=dict(role="assistant", content="done"), finish_reason="stop")])
        else:
            name, args = call
            arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=True)
            yield dict(choices=[dict(delta=dict(role="assistant", tool_calls=[dict(index=0,
                id="call-{}".format(len(self.requests)), type="function", function=dict(name=name, arguments=arguments))]),
                finish_reason="tool_calls")])


async def loop_harness(calls, config=None):
    ctx, model = Context(), ScriptedModel(calls)
    ctx.set_service("llm", model)
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(AgentPlugin)
    await ctx.plugin(AgentLoopPlugin)
    await ctx.plugin(RepeatToolReminderPlugin, config or {})
    for name in ("probe", "other"):
        ctx.get("tools").register(dict(name=name, description="fixture", parameters={},
            execute=lambda _args, _exec: [dict(type="text", text="ok")],
            output=dict(schema={}, render=lambda _args, value: value)))
    return ctx, model


def reminders(agent):
    return [event["data"] for event in agent.session.events if event["type"] == "user/message"
            and event["data"].get("source", {}).get("plugin") == "repeat-tool-reminder"]


@pytest.mark.asyncio
async def test_actual_agent_loop_escalation_and_next_request_context():
    ctx, model = await loop_harness([("probe", dict(q=1)) for _ in range(5)] + [None])
    handle = await ctx.get("agent_loop").create("repeat-loop")
    try:
        handle.agent.followup("go")
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        found = reminders(handle.agent)
        assert len(found) == 2
        assert found[0]["content"][0]["text"] == GENTLE_REMINDER
        assert '- arguments: {"q":1}' in found[1]["content"][0]["text"]
        assert found[0]["source"]["summary"] == "probe \u00d7 3"
        assert found[1]["source"]["summary"] == "probe \u00d7 5"
        assert GENTLE_REMINDER in str(model.requests[3])
        assert "consecutive_calls: 5" in str(model.requests[5])
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["deny", "block", "replace"])
async def test_actual_agent_loop_policy_outcomes_keep_reminder(decision):
    ctx, model = await loop_harness([("probe", dict(q=1))] * 2 + [None], dict(thresholds=[2]))
    if decision == "deny":
        ctx.on("tools/pre-execute", lambda *_: dict(kind="deny", reason="sealed"))
    elif decision == "block":
        ctx.on("tools/post-execute", lambda *_: dict(kind="block", feedback=[dict(type="text", text="blocked")]))
    else:
        ctx.on("tools/post-execute", lambda *_: dict(kind="accept", value=[dict(type="text", text="replaced")]))
    handle = await ctx.get("agent_loop").create("repeat-policy")
    try:
        handle.agent.followup("go")
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        assert len(reminders(handle.agent)) == 1
        assert GENTLE_REMINDER in str(model.requests[2])
        results = [e["data"]["message"]["content"][0] for e in handle.agent.session.events if e["type"] == "tool/result"]
        assert len(results) == 2
        assert all(result.get("isError", False) == (decision != "replace") for result in results)
        assert ("sealed" if decision == "deny" else "blocked" if decision == "block" else "replaced") in str(results)
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_agent_loop_new_user_resets_and_new_agent_same_id_starts_fresh():
    calls = [("probe", {}), ("probe", {}), None, ("probe", {}), None, ("probe", {}), None]
    ctx, _model = await loop_harness(calls)
    first = await ctx.get("agent_loop").create("reused")
    try:
        first.agent.followup("first prompt")
        await asyncio.wait_for(first.agent.when_idle(), 3)
        first.agent.followup("second prompt")
        await asyncio.wait_for(first.agent.when_idle(), 3)
        assert not reminders(first.agent)
        await first.dispose()
        second = await ctx.get("agent_loop").create("reused")
        try:
            second.agent.followup("third prompt")
            await asyncio.wait_for(second.agent.when_idle(), 3)
            assert not reminders(second.agent)
        finally:
            await second.dispose()
    finally:
        await first.dispose()
        await ctx.fiber.dispose()


def test_upstream_bug_allowance_requires_exact_input_target_and_output():
    from scripts.repeat_tool_oracle import reviewed_proto_difference, PROTO_CASE, PROTO_TARGET, PROTO_NOTICE
    notice = dict(content=[dict(type="text", text=PROTO_NOTICE)], source=dict(kind="plugin",
        plugin="repeat-tool-reminder", form="notice", summary="probe \u00d7 2"))
    upstream = dict(mode="proto-key-loss", notices=[notice], requests=[[], [], [PROTO_NOTICE]], results=[dict(content="ok")])
    python = dict(upstream, notices=[], requests=[[], [], []])
    assert reviewed_proto_difference(upstream, python, PROTO_CASE, PROTO_TARGET)
    assert not reviewed_proto_difference(upstream, python, PROTO_CASE, "other target")
    assert not reviewed_proto_difference(upstream, python, dict(PROTO_CASE, config=dict(thresholds=[3])), PROTO_TARGET)
    assert not reviewed_proto_difference(upstream, dict(python, results=[]), PROTO_CASE, PROTO_TARGET)
    assert not reviewed_proto_difference(dict(upstream, unexpected="extra"), python, PROTO_CASE, PROTO_TARGET)


@pytest.mark.asyncio
async def test_text_agent_input_is_identified_as_user_before_pre_step():
    ctx, _model = await loop_harness([None])
    captured = []
    async def observe(payload, next_fn):
        captured.extend(payload["messages"])
        return await next_fn()
    ctx.on("agent/pre-step", observe)
    handle = await ctx.get("agent_loop").create("text-input")
    try:
        message_id = handle.agent.followup("typed input")
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        user = next(message for message in captured if message.get("id") == message_id)
        assert user["role"] == "user" and user["source"] == dict(kind="user")
        assert user["content"] == [dict(type="text", text="typed input")]
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()
