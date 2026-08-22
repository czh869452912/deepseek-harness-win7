from typing import Any, Dict, List, Optional, Set


class InstructionState:
    def __init__(self):
        self.versions: Dict[str, int] = {}
        self.touched_paths: Set[str] = set()

    def update_touch(self, file_path: str) -> None:
        self.touched_paths.add(file_path)
        self.versions[file_path] = self.versions.get(file_path, 0) + 1
