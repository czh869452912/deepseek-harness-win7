import os
from typing import Any, Dict, List, Optional


DEFAULT_INSTRUCTION_CANDIDATES = [
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".agent-instructions.md",
    "agents.md",
]


class ResolvedConfig:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.max_bytes: int = int(cfg.get("maxBytes", 65536))
        self.max_source_bytes: int = int(cfg.get("maxSourceBytes", 131072))
        self.candidates: List[str] = list(cfg.get("candidates", DEFAULT_INSTRUCTION_CANDIDATES))
        self.local_candidates: List[str] = list(cfg.get("localInstructionFileCandidates", []))
        self.project_root_markers: List[str] = list(cfg.get("projectRootMarkers", [".git", "package.json", "pyproject.toml", "AGENTS.md"]))
        self.dsh_home: Optional[str] = cfg.get("dshHome")
