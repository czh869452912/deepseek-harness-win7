import os
import shutil
import tempfile
import pytest
from dsh.context.agent_instructions import AgentInstructionsPlugin, AgentInstructionsService
from dsh.cordis.context import Context
from dsh.core.persona import PersonaPlugin


@pytest.fixture
def temp_workspace():
    tmp = tempfile.mkdtemp(prefix="dsh_inst_test_")
    # Write a mock AGENTS.md
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
    # Creative mode persona (complete=False)
    ctx.plugin(PersonaPlugin, config={"text": "You are a helpful assistant."})
    ctx.plugin(AgentInstructionsPlugin)

    # Change directory temporarily or test with cwd
    orig_cwd = os.getcwd()
    os.chdir(temp_workspace)
    try:
        assembled = await ctx.waterfall("agent/prompt-assemble", "Base prompt")
        assert "Base prompt" in assembled
        assert "# Project Workspace Instructions" in assembled
        assert "Rule 1: Strict Python 3.8" in assembled
    finally:
        os.chdir(orig_cwd)


@pytest.mark.asyncio
async def test_instructions_suppressed_in_minimal_mode(temp_workspace):
    ctx = Context()
    # Minimal mode persona (complete=True)
    ctx.plugin(PersonaPlugin, config={"text": "Exclusive prompt.", "complete": True})
    ctx.plugin(AgentInstructionsPlugin)

    orig_cwd = os.getcwd()
    os.chdir(temp_workspace)
    try:
        assembled = await ctx.waterfall("agent/prompt-assemble", "Base prompt")
        # Minimal mode persona must remain completely exclusive!
        assert assembled == "Exclusive prompt."
        assert "Project Workspace Instructions" not in assembled
    finally:
        os.chdir(orig_cwd)
