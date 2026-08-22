from typing import Any, Dict, List, Optional, Set
from dsh.context.agent_instructions.digest import instruction_content_sha1, trimmed_instruction_digest
from dsh.context.agent_instructions.render import instruction_scope_key


class InstructionState:
    def __init__(self):
        self.versions: Dict[str, int] = {}
        self.touched_paths: Set[str] = set()

    def update_touch(self, file_path: str) -> None:
        self.touched_paths.add(file_path)
        self.versions[file_path] = self.versions.get(file_path, 0) + 1


def baseline_instruction_state(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    changes: Dict[str, Any] = {}
    versions: Dict[str, Any] = {}
    for file_item in files:
        digest = instruction_content_sha1(file_item["content"])
        scope = instruction_scope_key(file_item["displayPath"])
        change = {
            "action": "set",
            "scope": scope,
            "path": file_item["displayPath"],
            "digest": digest,
        }
        changes[scope] = change
        versions[scope] = {
            "path": file_item["displayPath"],
            "version": file_item.get("version", 1),
            "digest": digest,
            "trimmedDigest": trimmedInstructionDigest(file_item["content"]) if "trimmedInstructionDigest" in globals() else trimmed_instruction_digest(file_item["content"]),
        }
    return {"changes": changes, "versions": versions}
