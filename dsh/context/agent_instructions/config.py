import json
import os
from typing import Any, Dict, List, Optional, Set

DEFAULT_PROJECT_ROOT_MARKERS = [".git"]
DEFAULT_INSTRUCTION_FILE_CANDIDATES = ["AGENTS.md", "CLAUDE.md"]
DEFAULT_LOCAL_INSTRUCTION_FILE_CANDIDATES = ["AGENTS.local.md", "CLAUDE.local.md"]
DEFAULT_MAX_SOURCE_BYTES = 1_048_576
RESERVED_PATH_SEGMENTS = {"", ".", ".."}

# Backward compatibility alias
DEFAULT_INSTRUCTION_CANDIDATES = DEFAULT_INSTRUCTION_FILE_CANDIDATES


def resolve_dsh_home(dsh_home: Optional[str] = None) -> str:
    if dsh_home:
        return os.path.abspath(os.path.expanduser(dsh_home))
    env_home = os.environ.get("DSH_HOME")
    if env_home:
        return os.path.abspath(os.path.expanduser(env_home))
    return os.path.abspath(os.path.expanduser("~/.dsh"))


def resolve_instruction_file_candidates(candidates: Optional[List[str]], fallback: List[str]) -> List[str]:
    c_list = candidates if candidates is not None else fallback
    res = []
    for c in c_list:
        if c in RESERVED_PATH_SEGMENTS:
            continue
        if "\\" in c or "/" in c:
            continue
        res.append(c)
    return res


class ResolvedDiscoveryConfig:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.dsh_home: str = resolve_dsh_home(cfg.get("dshHome") or cfg.get("dsh_home"))
        markers = cfg.get("projectRootMarkers") or cfg.get("project_root_markers")
        self.project_root_markers: List[str] = list(markers) if markers is not None else list(DEFAULT_PROJECT_ROOT_MARKERS)
        self.instruction_file_candidates: List[str] = resolve_instruction_file_candidates(
            cfg.get("instructionFileCandidates") or cfg.get("candidates"),
            DEFAULT_INSTRUCTION_FILE_CANDIDATES
        )
        self.local_instruction_file_candidates: List[str] = resolve_instruction_file_candidates(
            cfg.get("localInstructionFileCandidates") or cfg.get("local_candidates"),
            DEFAULT_LOCAL_INSTRUCTION_FILE_CANDIDATES
        )

    @property
    def candidates(self) -> List[str]:
        return self.instruction_file_candidates


class ResolvedConfig(ResolvedDiscoveryConfig):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.max_bytes: int = int(cfg.get("maxBytes", cfg.get("max_bytes", 65536)))
        self.max_source_bytes: int = int(cfg.get("maxSourceBytes", cfg.get("max_source_bytes", DEFAULT_MAX_SOURCE_BYTES)))


def workspace_baseline_identity(config: ResolvedConfig, cwd: str, project_root: str) -> str:
    try:
        rel_root = os.path.relpath(project_root, cwd)
    except ValueError:
        rel_root = project_root
    return json.dumps({
        "projectRoot": rel_root,
        "projectRootMarkers": config.project_root_markers,
        "maxBytes": config.max_bytes,
        "maxSourceBytes": config.max_source_bytes,
        "instructionFileCandidates": config.instruction_file_candidates,
        "localInstructionFileCandidates": config.local_instruction_file_candidates,
    }, sort_keys=True)


def resolve_config(config: Optional[Dict[str, Any]] = None) -> ResolvedConfig:
    return ResolvedConfig(config)


def resolve_discovery_config(config: Optional[Dict[str, Any]] = None) -> ResolvedDiscoveryConfig:
    return ResolvedDiscoveryConfig(config)
