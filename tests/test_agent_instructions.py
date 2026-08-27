import os
import shutil
import tempfile
import pytest
from dsh.context.agent_instructions import AgentInstructionsPlugin, AgentInstructionsService
from dsh.context.agent_instructions.config import ResolvedConfig, workspace_baseline_identity
from dsh.context.agent_instructions.files import dedup_instruction_files_by_directory, load_baseline_instruction_set
from dsh.context.agent_instructions.render import (
    candidate_scope_key,
    decode_scope_key,
    instruction_scope_key,
    render_workspace_context,
)
from dsh.cordis.context import Context
from dsh.core.persona import PersonaPlugin


@pytest.fixture
def temp_workspace():
    tmp = tempfile.mkdtemp(prefix="dsh_inst_test_")
    with open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8") as f:
        f.write("# Project Rules\n\nRule 1: Strict Python 3.8\nRule 2: Windows 7 SP1\n")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_instructions_discovery_and_render(temp_workspace):
    svc = AgentInstructionsService()
    files = svc.discover_and_read(temp_workspace)
    assert len(files) == 1
    assert files[0]["path"] == "AGENTS.md"
    assert "Rule 1: Strict Python 3.8" in files[0]["content"]

    rendered = svc.render_section(temp_workspace)
    assert "# Project Workspace Instructions" in rendered
    assert "## Instructions from AGENTS.md" in rendered


@pytest.mark.asyncio
async def test_instructions_prompt_assembly_injection(temp_workspace):
    ctx = Context()
    await ctx.registry.plugin(PersonaPlugin, config={"text": "You are a helpful assistant."})
    await ctx.registry.plugin(AgentInstructionsPlugin)

    orig_cwd = os.getcwd()
    os.chdir(temp_workspace)
    try:
        assembled = await ctx.waterfall("agent/prompt-assemble", "Base prompt", lambda value: value)
        assert "Base prompt" in assembled
        assert "# Project Workspace Instructions" in assembled
        assert "Rule 1: Strict Python 3.8" in assembled
    finally:
        os.chdir(orig_cwd)


@pytest.mark.asyncio
async def test_instructions_suppressed_in_minimal_mode(temp_workspace):
    ctx = Context()
    await ctx.registry.plugin(PersonaPlugin, config={"text": "Exclusive prompt.", "complete": True})
    await ctx.registry.plugin(AgentInstructionsPlugin)

    orig_cwd = os.getcwd()
    os.chdir(temp_workspace)
    try:
        assembled = await ctx.waterfall("agent/prompt-assemble", "Base prompt", lambda value: value)
        assert assembled == "Exclusive prompt."
        assert "Project Workspace Instructions" not in assembled
    finally:
        os.chdir(orig_cwd)


def test_instructions_1to1_helpers(temp_workspace):
    # Test deduplication
    files = [
        {"displayPath": "src/AGENTS.md", "content": "  Rule 1  \n"},
        {"displayPath": "src/CLAUDE.md", "content": "Rule 1"},  # duplicate trimmed content in same dir
    ]
    deduped = dedup_instruction_files_by_directory(files)
    assert len(deduped) == 1
    assert deduped[0]["displayPath"] == "src/AGENTS.md"

    # Test scope keys
    scope = candidate_scope_key(".", "AGENTS.md")
    decoded = decode_scope_key(scope)
    assert decoded["directory"] == "."
    assert decoded["candidateName"] == "AGENTS.md"

    # Test render_workspace_context with system-reminder frame
    rendered = render_workspace_context([
        {"displayPath": "AGENTS.md", "content": "Strict instructions"}
    ], {"maxBytes": 1000})
    assert "<system-reminder>" in rendered["text"]
    assert "Strict instructions" in rendered["text"]
    assert "</system-reminder>" in rendered["text"]

    # Test baseline identity
    cfg = ResolvedConfig({"maxBytes": 5000})
    identity = workspace_baseline_identity(cfg, temp_workspace, temp_workspace)
    assert "projectRoot" in identity
    assert "maxBytes" in identity
