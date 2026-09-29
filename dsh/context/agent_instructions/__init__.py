"""
Workspace Agent Instructions Subsystem (`@deepseek-ai/dsh-agent-instructions`).
Discovers project instructions (AGENTS.md, CLAUDE.md, etc.) in workspace
and injects them into system prompt assembly, refreshing dynamically on file touch.
"""

import os
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.context.agent_instructions.config import (
    DEFAULT_INSTRUCTION_CANDIDATES,
    DEFAULT_INSTRUCTION_FILE_CANDIDATES,
    ResolvedConfig,
    resolve_config,
)
from dsh.context.agent_instructions.files import (
    discover_and_read_files,
    discover_baseline_instruction_files,
    find_project_root,
    load_baseline_instruction_set,
)
from dsh.context.agent_instructions.render import (
    render_workspace_context,
    render_workspace_instruction_set,
)
from dsh.context.agent_instructions.state import InstructionState

name = "agent-instructions"


class AgentInstructionsService:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = resolve_config(config)
        self.max_bytes = self.config.max_bytes
        self.candidates = self.config.instruction_file_candidates
        self.state = InstructionState()

    def discover_and_read(self, cwd: Optional[str] = None) -> List[Dict[str, str]]:
        work_dir = cwd or os.getcwd()
        return discover_and_read_files(work_dir, self.candidates, self.max_bytes)

    def render_section(self, cwd: Optional[str] = None) -> str:
        files = self.discover_and_read(cwd)
        if not files:
            return ""

        parts = []
        for f in files:
            parts.append(f"## Instructions from {f['path']}\n\n{f['content']}")

        return "\n\n# Project Workspace Instructions\n\n" + "\n\n".join(parts)


class AgentInstructionsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-agent-instructions`: Discovers workspace instruction files.
    """

    id = "agent-instructions"
    name = "@deepseek-ai/dsh-agent-instructions"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.service = AgentInstructionsService(config)

    def apply(self, ctx: Any) -> None:
        from .runtime import InstructionRuntime
        InstructionRuntime(ctx, self.service.config)


__all__ = [
    "AgentInstructionsPlugin",
    "AgentInstructionsService",
    "ResolvedConfig",
    "discover_baseline_instruction_files",
    "load_baseline_instruction_set",
    "render_workspace_context",
    "name",
]
