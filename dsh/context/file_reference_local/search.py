import os
from typing import Any, Dict, List, Optional


DEFAULT_FILE_SEARCH_EXCLUDED_DIRECTORIES = [".git", "node_modules", "__pycache__", ".venv"]
DEFAULT_FILE_SEARCH_MAX_RESULTS = 20
DEFAULT_FILE_SEARCH_MAX_ENTRIES = 5000


class WorkspaceFileSearch:
    def __init__(self, cwd: str, config: Optional[Dict[str, Any]] = None):
        self.cwd = os.path.abspath(cwd)
        cfg = config or {}
        self.max_results = int(cfg.get("maxResults", DEFAULT_FILE_SEARCH_MAX_RESULTS))
        self.max_entries = int(cfg.get("maxEntries", DEFAULT_FILE_SEARCH_MAX_ENTRIES))
        self.excluded_directories = set(cfg.get("excludedDirectories", DEFAULT_FILE_SEARCH_EXCLUDED_DIRECTORIES))
        self._cache: Optional[List[str]] = None

    def invalidate(self) -> None:
        self._cache = None

    def list_candidates(self, query: str = "") -> List[Dict[str, str]]:
        if self._cache is None:
            items = []
            count = 0
            for dirpath, dirnames, filenames in os.walk(self.cwd):
                dirnames[:] = [d for d in dirnames if d not in self.excluded_directories and not d.startswith(".")]
                for fname in filenames:
                    if fname.startswith("."):
                        continue
                    full = os.path.join(dirpath, fname)
                    rel = os.path.relpath(full, self.cwd).replace("\\", "/")
                    items.append(rel)
                    count += 1
                    if count >= self.max_entries:
                        break
                if count >= self.max_entries:
                    break
            self._cache = items

        q_lower = query.lower()
        results = []
        for path in self._cache:
            if not q_lower or q_lower in path.lower():
                results.append({"path": path, "name": os.path.basename(path)})
                if len(results) >= self.max_results:
                    break
        return results
