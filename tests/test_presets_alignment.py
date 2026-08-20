import sys
import pytest
from dsh.harness import build_harness


def test_minimal_preset_alignment():
    ctx = build_harness(mode="minimal", verbose=False)
    tools = ctx.get("tools")
    schemas = tools.get_schemas()
    tool_names = [s["function"]["name"] for s in schemas]

    # Minimal mode must have exactly 2 tools: str_replace_editor and shell
    assert "str_replace_editor" in tool_names
    expected_shell = "pwsh" if sys.platform == "win32" else "bash"
    assert expected_shell in tool_names
    assert len(schemas) == 2

    # Persona is complete
    persona = ctx.get("persona")
    assert persona is not None
    assert persona.complete is True

    # No compaction or skill in minimal mode
    assert not ctx.has("compaction")
    assert "skill" not in tool_names


def test_standard_preset_alignment():
    ctx = build_harness(mode="standard", verbose=False)
    tools = ctx.get("tools")
    schemas = tools.get_schemas()
    tool_names = set(s["function"]["name"] for s in schemas)

    # Engineering tools
    assert "str_replace_editor" in tool_names
    assert ("pwsh" if sys.platform == "win32" else "bash") in tool_names
    assert "glob" in tool_names
    assert "grep" in tool_names
    assert "ask_user_question" in tool_names
    assert "todo_write" in tool_names
    assert "skill" in tool_names
    assert "exit_plan_mode" in tool_names
    assert "get_goal" in tool_names
    assert "create_goal" in tool_names
    assert "update_goal" in tool_names

    # Standard mode does NOT expose cordis manager tools
    assert "cordis_list_plugins" not in tool_names
    assert "cordis_inspect_context" not in tool_names

    # Services
    assert ctx.has("compaction")
    assert ctx.has("tool_result_pruner")
    assert ctx.has("agent_instructions")
    assert ctx.has("skills")
    assert ctx.has("plan_mode")
    assert ctx.has("goals")

    # Persona
    persona = ctx.get("persona")
    assert persona is not None
    prompt = persona.get_prompt()
    assert "You are a coding agent" in prompt
    assert "editing-cordis-compositions" not in prompt


def test_creative_preset_alignment():
    ctx = build_harness(mode="creative", verbose=False)
    tools = ctx.get("tools")
    schemas = tools.get_schemas()
    tool_names = set(s["function"]["name"] for s in schemas)

    # Engineering tools
    assert "str_replace_editor" in tool_names
    assert ("pwsh" if sys.platform == "win32" else "bash") in tool_names
    assert "glob" in tool_names
    assert "grep" in tool_names
    assert "ask_user_question" in tool_names
    assert "todo_write" in tool_names
    assert "skill" in tool_names
    assert "exit_plan_mode" in tool_names

    # Cordis manager tools
    assert "cordis_list_plugins" in tool_names
    assert "cordis_inspect_context" in tool_names
    assert "cordis_unload_plugin" in tool_names
    assert "cordis_dump_config" in tool_names

    # Services
    assert ctx.has("compaction")
    assert ctx.has("tool_result_pruner")
    assert ctx.has("agent_instructions")
    assert ctx.has("skills")
    assert ctx.has("plan_mode")

    # Persona
    persona = ctx.get("persona")
    assert persona is not None
    prompt = persona.get_prompt()
    assert "DeepSeek Harness" in prompt
    assert "editing-cordis-compositions" in prompt
