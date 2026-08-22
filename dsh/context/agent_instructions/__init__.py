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
        ctx.set_service("agent_instructions", self.service)

        async def prompt_assembler(prompt: str, *args: Any, **kwargs: Any) -> str:
            # Check if persona was set to complete=True (minimal mode)
            persona = ctx.get("persona") if ctx.has("persona") else None
            if persona and getattr(persona, "complete", False):
                return prompt

            section = self.service.render_section()
            if section:
                return f"{prompt}\n{section}"
            return prompt

        ctx.on("agent/prompt-assemble", prompt_assembler)

        # Listen to tool execution results to refresh instructions when instruction files are edited
        def on_tool_result(exec_data: Any, result_data: Any = None) -> None:
            tool_name = exec_data.get("name") if isinstance(exec_data, dict) else getattr(exec_data, "name", "")
            if tool_name in ("write", "edit", "str_replace_editor"):
                args = exec_data.get("arguments", {}) if isinstance(exec_data, dict) else getattr(exec_data, "arguments", {})
                file_path = args.get("file_path") or args.get("path")
                if file_path and any(candidate in file_path for candidate in DEFAULT_INSTRUCTION_FILE_CANDIDATES):
                    self.service.state.update_touch(file_path)

        ctx.on("tools/result", on_tool_result)


__all__ = [
    "AgentInstructionsPlugin",
    "AgentInstructionsService",
    "ResolvedConfig",
    "discover_baseline_instruction_files",
    "load_baseline_instruction_set",
    "render_workspace_context",
    "name",
]
