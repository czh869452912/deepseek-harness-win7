import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.session import Session, SessionStore, SessionPlugin
from dsh.core.tools import ToolsPlugin
from dsh.skill.skill_service import (
    SkillService,
    SkillDefinition,
    is_skill_name,
    render_skill_content,
    escape_text,
    escape_attr,
)
from dsh.skill.tool_skill import (
    ToolSkillPlugin,
    catalog_description,
    digest_catalog_entries,
    render_catalog_message,
    render_catalog_update,
)


def fake_agent(ctx, name="agent-1", cwd=None):
    sess_store = ctx.get("sessions")
    session = sess_store.create(name)
    agent = Agent(agent_id=name, session=session, ctx=ctx)
    ctx.get("agents").enter(agent)
    return agent


@pytest.fixture
def skill_ctx():
    ctx = Context()
    tools_plugin = ToolsPlugin()
    tools_plugin.apply(ctx)
    sess_plugin = SessionPlugin()
    sess_plugin.apply(ctx)
    agent_plugin = AgentPlugin()
    agent_plugin.apply(ctx)
    skill_svc = SkillService(ctx)
    ctx.set_service("skills", skill_svc)
    tool_plugin = ToolSkillPlugin({"catalogDescriptionMaxLength": 50})
    tool_plugin.apply(ctx)
    return ctx


def test_is_skill_name():
    assert is_skill_name("git-commit") is True
    assert is_skill_name("test-skill-123") is True
    assert is_skill_name("TestSkill") is False
    assert is_skill_name("git_commit") is False
    assert is_skill_name("") is False


def test_catalog_description_truncation():
    raw = "A very long skill description that exceeds fifty characters by a lot"
    res = catalog_description(raw, 50)
    assert len(res) <= 50
    assert res.endswith("...")

    short = "Short description"
    assert catalog_description(short, 50) == "Short description"


def test_render_skill_content():
    skill = SkillDefinition(
        name="test-skill",
        description="A test skill",
        content="Follow these instructions:\n1. Run tests\n2. Commit",
        provider="filesystem",
        resource_base={"kind": "directory", "path": "/path/to/skill"},
    )
    rendered = render_skill_content(skill)
    assert '<skill_content name="test-skill">' in rendered
    assert '<skill_resources>' in rendered
    assert 'Base directory for this skill: /path/to/skill' in rendered
    assert '<skill_instructions>' in rendered
    assert 'Follow these instructions:' in rendered
    assert '</skill_content>' in rendered


@pytest.mark.asyncio
async def test_tool_skill_execution(skill_ctx):
    ctx = skill_ctx
    skill_svc: SkillService = ctx.get("skills")
    skill_svc.register_skill(SkillDefinition(
        name="code-review",
        description="Perform thorough code review",
        content="Check security and style.",
        model_invocable=True,
    ))
    skill_svc.register_skill(SkillDefinition(
        name="user-only",
        description="Manual trigger only",
        content="Do not call from model",
        model_invocable=False,
    ))

    agent = fake_agent(ctx, "agent-sk")
    tools_svc = ctx.get("tools")

    # Load valid skill
    res = await tools_svc.execute({
        "name": "skill",
        "arguments": {"name": "code-review"},
        "agent": agent,
    })
    assert res.is_error is False
    assert '<skill_content name="code-review">' in res.content[0]["text"]

    # Load invalid / non-model skill
    res_bad = await tools_svc.execute({
        "name": "skill",
        "arguments": {"name": "user-only"},
        "agent": agent,
    })
    assert "not available for model invocation" in res_bad.content[0]["text"] or res_bad.is_error

    # Load unknown skill
    res_unknown = await tools_svc.execute({
        "name": "skill",
        "arguments": {"name": "nonexistent"},
        "agent": agent,
    })
    assert "unknown or no longer available" in res_unknown.content[0]["text"] or res_unknown.is_error