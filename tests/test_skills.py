import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.plugins.skill_filesystem import SkillFilesystemPlugin
from dsh.plugins.tool_skill import ToolSkillPlugin
from dsh.services.skills import parse_skill_file, SkillDefinition, SkillService
from dsh.services.tools import ToolsService


def test_parse_skill_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_file = os.path.join(tmpdir, "SKILL.md")
        content = (
            "---\n"
            "name: test-skill\n"
            "description: A test skill for verification\n"
            "when_to_use: Use when testing skills\n"
            "---\n"
            "# Test Skill Instructions\n"
            "Step 1: Do something.\n"
        )
        with open(skill_file, "w", encoding="utf-8") as f:
            f.write(content)

        parsed = parse_skill_file(skill_file, default_name="test-skill")
        assert parsed is not None
        assert parsed.name == "test-skill"
        assert parsed.description == "A test skill for verification"
        assert parsed.when_to_use == "Use when testing skills"
        assert "# Test Skill Instructions" in parsed.content
        assert '<skill_content name="test-skill">' in parsed.render_content()


@pytest.mark.asyncio
async def test_skill_filesystem_and_tool_plugin():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))

    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = os.path.join(tmpdir, "skills", "sample-skill")
        os.makedirs(skills_dir, exist_ok=True)
        skill_md = os.path.join(skills_dir, "SKILL.md")
        with open(skill_md, "w", encoding="utf-8") as f:
            f.write("---\nname: sample-skill\ndescription: Sample skill for pytest\n---\nSample Instructions")

        # Plugin setup
        ctx.plugin(SkillFilesystemPlugin, config={"customSkillDirs": [os.path.join(tmpdir, "skills")]})
        tool_skill = ctx.plugin(ToolSkillPlugin)

        skills = ctx.skills.list_skills()
        assert len(skills) >= 1
        found_names = [s.name for s in skills]
        assert "sample-skill" in found_names

        # Test prompt assembly hook
        assembled = tool_skill.on_prompt_assemble("Base Prompt")
        assert "<available_skills>" in assembled
        assert "- sample-skill: Sample skill for pytest" in assembled

        # Test loading skill via tool
        tool_res = tool_skill.handle_load_skill("sample-skill", ctx=ctx)
        assert '<skill_content name="sample-skill">' in tool_res
        assert "Sample Instructions" in tool_res

        # Test slash command injection hook
        payload = {
            "messages": [
                {"role": "user", "content": "/sample-skill Please follow this skill"}
            ]
        }
        res_payload = await tool_skill.on_pre_step(payload)
        injected_content = res_payload["messages"][0]["content"]
        assert "[Injected Skill Instructions]" in injected_content
        assert "Sample Instructions" in injected_content
