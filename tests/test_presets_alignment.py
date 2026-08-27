import sys
import pytest
from dsh.harness import build_harness


def _preset_tools(ctx):
    tools = ctx.get("tools")
    rows = {}
    for fiber in ctx.registry.list_fibers():
        try:
            for row in tools.schemas(scope=fiber.ctx):
                rows[row["name"]] = row
        except Exception:
            continue
    return list(rows.values())


def _has_service(ctx, name):
    if ctx.has(name):
        return True
    return any(f.ctx.has(name) for f in ctx.registry.list_fibers())


def test_minimal_preset_alignment():
    ctx = build_harness(mode="minimal", verbose=False)
    schemas = _preset_tools(ctx)
    tool_names = [s["name"] for s in schemas]

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
    schemas = _preset_tools(ctx)
    tool_names = set(s["name"] for s in schemas)

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
    assert _has_service(ctx, "compaction")
    assert _has_service(ctx, "tool_result_pruner")
    assert _has_service(ctx, "agent_instructions")
    assert _has_service(ctx, "skills")
    assert _has_service(ctx, "plan_mode")
    assert _has_service(ctx, "goals")

    # Persona
    persona = ctx.get("persona")
    assert persona is not None
    prompt = persona.get_prompt()
    assert "You are a coding agent" in prompt
    assert "editing-cordis-compositions" not in prompt


def test_creative_preset_alignment():
    ctx = build_harness(mode="creative", verbose=False)
    schemas = _preset_tools(ctx)
    tool_names = set(s["name"] for s in schemas)

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
    assert _has_service(ctx, "compaction")
    assert _has_service(ctx, "tool_result_pruner")
    assert _has_service(ctx, "agent_instructions")
    assert _has_service(ctx, "skills")
    assert _has_service(ctx, "plan_mode")

    # Persona
    persona = ctx.get("persona")
    assert persona is not None
    prompt = persona.get_prompt()
    assert "DeepSeek Harness" in prompt
    assert "editing-cordis-compositions" in prompt
