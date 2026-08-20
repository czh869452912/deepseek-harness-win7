"""
Workspace Agent Instructions Subsystem (`@deepseek-ai/dsh-agent-instructions`).
Discovers project instructions (AGENTS.md, CLAUDE.md, .cursorrules) in workspace
and injects them into system prompt assembly.
"""

import os
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


DEFAULT_INSTRUCTION_CANDIDATES = [
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".agent-instructions.md",
    "agents.md",
]


class AgentInstructionsService:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.max_bytes: int = int(cfg.get("maxBytes", 65536))
        self.candidates: List[str] = list(cfg.get("candidates", DEFAULT_INSTRUCTION_CANDIDATES))

    def discover_and_read(self, cwd: Optional[str] = None) -> List[Dict[str, str]]:
        work_dir = cwd or os.getcwd()
        results: List[Dict[str, str]] = []
        total_bytes = 0
        seen_paths = set()

        for name in self.candidates:
            file_path = os.path.join(work_dir, name)
            if os.path.isfile(file_path):
                real_key = os.path.normcase(os.path.abspath(file_path))
                if real_key in seen_paths:
                    continue
                seen_paths.add(real_key)

                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    
                    encoded = content.encode("utf-8")
                    if total_bytes + len(encoded) > self.max_bytes:
                        remaining = max(0, self.max_bytes - total_bytes)
                        content = encoded[:remaining].decode("utf-8", errors="ignore") + "\n\n[... truncated by maxBytes limit]"
                        results.append({"path": name, "content": content})
                        break
                    
                    total_bytes += len(encoded)
                    results.append({"path": name, "content": content})
                except Exception:
                    pass

        return results

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
            # Check if persona was set to complete=True
            persona = ctx.get("persona")
            if persona and getattr(persona, "complete", False):
                return prompt

            section = self.service.render_section()
            if section:
                return f"{prompt}\n{section}"
            return prompt

        ctx.on("agent/prompt-assemble", prompt_assembler)
