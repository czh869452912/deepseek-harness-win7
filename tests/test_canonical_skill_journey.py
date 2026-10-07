from dsh.core.system_prompt import SystemPrompt as SourceToolsPrompt
import asyncio
from types import SimpleNamespace

import pytest

from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentRegistry
from dsh.core.scope import create_scope, ScopeKey
from dsh.core.session import Session
from dsh.core.tools import ToolsPlugin
from dsh.fs.fs_local import FsLocalPlugin
from dsh.llm.message import create_user_message


async def setup(tmp_path):
    ctx = Context()
    ctx.set_service("agents", AgentRegistry(ctx))
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(FsLocalPlugin)
    await ctx.plugin(resolve_harness_plugin("@deepseek-ai/dsh-skill"))
    fs_fiber = await ctx.plugin(resolve_harness_plugin("@deepseek-ai/dsh-skill-filesystem"), config={
        "customSkillDirs": [str(tmp_path)], "includeDefaultRoots": False,
        "watchPollIntervalMs": 10, "watchStabilityThresholdMs": 10})
    await ctx.plugin(resolve_harness_plugin("@deepseek-ai/dsh-tool-skill"))
    agent_ctx = create_scope(ctx, ScopeKey("agent")).ctx
    agent = Agent(Session("skill-journey"), ctx=agent_ctx)
    ctx.get("agents").register(agent)
    return ctx, agent, fs_fiber


def write_skill(path, body="first body", invocation=""):
    path.write_text("---\nname: sample\ndescription: A sample skill\n" + invocation + "---\n" + body, encoding="utf-8")


@pytest.mark.asyncio
async def test_real_filesystem_catalog_invocation_and_structured_tool(tmp_path):
    write_skill(tmp_path / "sample.md")
    ctx, agent, _ = await setup(tmp_path)
    try:
        message = create_user_message({"content": [dict(type='text', text="Please use /sample now")], 'source': dict(kind='user')})
        decision = await ctx.waterfall("agent/pre-step", {"agent": agent, "messages": [message]})
        assert [row["source"]["kind"] for row in decision["messages"]] == ["user", "skill-catalog", "skill-invocation"]
        assert message["content"][0]["text"] == "Please use /sample now"
        definition = ctx.get("tools").get("skill")
        result = await definition.execute({"name": "sample"}, SimpleNamespace(agent=agent, signal=None))
        assert result["content"] == "first body" and result["provider"] == "filesystem"
        assert result["resourceBase"]["path"] == str(tmp_path)
        for row in decision["messages"]:
            agent.session.append("user/message", row, surface_op="append")
        next_message = create_user_message({"content": [dict(type='text', text="Continue")], 'source': dict(kind='user')})
        next_decision = await ctx.waterfall("agent/pre-step", {"agent": agent, "messages": [next_message]})
        assert next_decision["messages"] == [next_message]
        # External plugin content cannot forge a direct-human gesture.
        external = create_user_message({"content": [dict(type='text', text="/sample")], "source": {"kind": "plugin", "plugin": "external"}})
        decision = await ctx.waterfall("agent/pre-step", {"agent": agent, "messages": [external]})
        assert not any(row["source"]["kind"] == "skill-invocation" for row in decision["messages"])
        other = Agent(Session("other"), ctx=create_scope(ctx, ScopeKey("other")).ctx)
        other_message = create_user_message({"content": [dict(type='text', text="New session")], 'source': dict(kind='user')})
        other_decision = await ctx.waterfall("agent/pre-step", {"agent": other, "messages": [other_message]})
        assert other_decision["messages"][-1]["source"]["kind"] == "skill-catalog"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_filesystem_change_invalidates_cache_and_disposal_removes_provider(tmp_path):
    path = tmp_path / "sample.md"
    write_skill(path)
    ctx, _, fiber = await setup(tmp_path)
    try:
        skills = ctx.get("skills")
        assert len(await skills.list()) == 1
        path.unlink()
        for _ in range(100):
            if not await skills.list():
                break
            await asyncio.sleep(0.01)
        assert await skills.list() == []
        write_skill(path, invocation="disable-model-invocation: true\nuser-invocable: false\n")
        for _ in range(100):
            if await skills.list():
                break
            await asyncio.sleep(0.01)
        assert (await skills.get("sample"))["invocation"] == {"modelInvocable": False, "userInvocable": False}
        await fiber.dispose()
        assert await skills.list() == []
    finally:
        await ctx.fiber.dispose()
