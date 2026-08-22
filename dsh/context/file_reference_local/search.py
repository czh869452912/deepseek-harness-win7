import os
from typing import Any, Dict, List, Optional, Set

DEFAULT_FILE_SEARCH_MAX_RESULTS = 20
DEFAULT_FILE_SEARCH_MAX_ENTRIES = 10_000
DEFAULT_FILE_SEARCH_EXCLUDED_DIRECTORIES = [".git", "node_modules"]


def subsequence_score(target: str, query: str) -> Optional[int]:
    target_index = 0
    gap = 0
    for char in query:
        found = target.find(char, target_index)
        if found < 0:
            return None
        gap += found - target_index
        target_index = found + 1
    return max(0, 100 - gap)


def score_candidate(candidate: Dict[str, str], query: str) -> Optional[int]:
    if not query:
        return 0
    path = candidate["path"].lower()
    last_slash = path.rfind("/")
    name = path if last_slash < 0 else path[last_slash + 1:]
    needle = query.lower()
    directory_bonus = 25 if candidate.get("kind") == "directory" else 0

    if name == needle:
        return 1000 + directory_bonus
    if name.startswith(needle):
        return 900 + directory_bonus
    if needle in name:
        return 700 + directory_bonus
    if needle in path:
        return 500 + directory_bonus

    subseq = subsequence_score(path, needle)
    if subseq is not None:
        return 300 + subseq + directory_bonus
    return None


def rank_candidates(
    candidates: List[Dict[str, str]], query: str, limit: int
) -> List[Dict[str, str]]:
    ranked = []
    for candidate in candidates:
        score = score_candidate(candidate, query)
        if score is not None:
            ranked.append((score, candidate))

    def sort_key(item: Any) -> Any:
        score, candidate = item
        kind_rank = 0 if candidate.get("kind") == "directory" else 1
        path_len = len(candidate["path"]) if query else 0
        return (-score, kind_rank, path_len, candidate["path"])

    ranked.sort(key=sort_key)
    return [item[1] for item in ranked[:limit]]


def visible_for_global_query(path: str, query: str) -> bool:
    if query.startswith(".") or "/." in query:
        return True
    return not any(segment.startswith(".") for segment in path.split("/"))


class WorkspaceFileSearch:
    def __init__(self, root: str, config: Optional[Dict[str, Any]] = None):
        self.root = os.path.abspath(root)
        cfg = config or {}
        self.max_results = int(cfg.get("maxResults", DEFAULT_FILE_SEARCH_MAX_RESULTS))
        self.max_entries = int(cfg.get("maxEntries", DEFAULT_FILE_SEARCH_MAX_ENTRIES))
        excluded = cfg.get("excludedDirectories", DEFAULT_FILE_SEARCH_EXCLUDED_DIRECTORIES)
        self.excluded_directories: Set[str] = set(excluded)
        self._index: Optional[List[Dict[str, str]]] = None
        self._disposed = False

    def invalidate(self) -> None:
        self._index = None

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self.invalidate()

    def list(self, raw_query: str = "", signal: Any = None) -> List[Dict[str, str]]:
        if self._disposed:
            return []
        query = raw_query.replace("\\", "/")
        slash = query.rfind("/")
        if not query or slash >= 0:
            directory = "" if slash < 0 else query[:slash + 1]
            fragment = "" if slash < 0 else query[slash + 1:]
            return self.list_directory(directory, fragment)

        indexed = self.ensure_index()
        filtered = [c for c in indexed if visible_for_global_query(c["path"], query)]
        return rank_candidates(filtered, query, self.max_results)

    def list_candidates(self, query: str = "") -> List[Dict[str, str]]:
        """Alias maintained for backward compatibility."""
        return self.list(query)

    def ensure_index(self) -> List[Dict[str, str]]:
        if self._index is not None:
            return self._index
        self._index = self.scan_workspace()
        return self._index

    def scan_workspace(self) -> List[Dict[str, str]]:
        indexed: List[Dict[str, str]] = []
        directories = [{"absolute": self.root, "relative": ""}]
        cursor = 0

        while cursor < len(directories) and len(indexed) < self.max_entries:
            curr = directories[cursor]
            cursor += 1
            abs_dir = curr["absolute"]
            rel_dir = curr["relative"]

            try:
                entries = sorted(os.listdir(abs_dir))
            except Exception:
                continue

            for name in entries:
                full_path = os.path.join(abs_dir, name)
                path = name if rel_dir == "" else f"{rel_dir}/{name}"

                if os.path.isdir(full_path):
                    if name in self.excluded_directories:
                        continue
                    indexed.append({"path": path, "kind": "directory", "name": name})
                    directories.append({"absolute": full_path, "relative": path})
                elif os.path.isfile(full_path):
                    indexed.append({"path": path, "kind": "file", "name": name})

                if len(indexed) >= self.max_entries:
                    break

        return indexed

    def list_directory(self, display_directory: str, fragment: str) -> List[Dict[str, str]]:
        if any(segment in self.excluded_directories for segment in display_directory.split("/") if segment):
            return []

        rel_path = "." if not display_directory else display_directory
        abs_target = os.path.abspath(os.path.join(self.root, rel_path))
        try:
            rel_check = os.path.relpath(abs_target, self.root)
            if rel_check.startswith(".."):
                return []
        except ValueError:
            return []

        try:
            entries = sorted(os.listdir(abs_target))
        except Exception:
            return []

        candidates: List[Dict[str, str]] = []
        for name in entries:
            if name.startswith(".") and not fragment.startswith("."):
                continue
            full_item = os.path.join(abs_target, name)
            if os.path.isdir(full_item):
                if name in self.excluded_directories:
                    continue
                candidates.append({"path": f"{display_directory}{name}", "kind": "directory", "name": name})
            elif os.path.isfile(full_item):
                candidates.append({"path": f"{display_directory}{name}", "kind": "file", "name": name})

        return rank_candidates(candidates, fragment, self.max_results)
