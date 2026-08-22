import os
from typing import Any, Dict, List, Optional


def find_project_root(cwd: str, markers: List[str]) -> str:
    current = os.path.abspath(cwd)
    while True:
        for marker in markers:
            if os.path.exists(os.path.join(current, marker)):
                return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.abspath(cwd)


def discover_and_read_files(work_dir: str, candidates: List[str], max_bytes: int) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    total_bytes = 0
    seen_paths = set()

    for name in candidates:
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
                if total_bytes + len(encoded) > max_bytes:
                    remaining = max(0, max_bytes - total_bytes)
                    content = encoded[:remaining].decode("utf-8", errors="ignore") + "\n\n[... truncated by maxBytes limit]"
                    results.append({"path": name, "content": content, "full_path": file_path})
                    break

                total_bytes += len(encoded)
                results.append({"path": name, "content": content, "full_path": file_path})
            except Exception:
                pass

    return results
