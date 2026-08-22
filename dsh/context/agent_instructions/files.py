import os
from typing import Any, Dict, List, Optional, Set, Tuple
from dsh.context.agent_instructions.config import (
    DEFAULT_INSTRUCTION_FILE_CANDIDATES,
    DEFAULT_MAX_SOURCE_BYTES,
    DEFAULT_PROJECT_ROOT_MARKERS,
    resolve_config,
    resolve_discovery_config,
)
from dsh.context.agent_instructions.digest import trimmed_instruction_digest
from dsh.context.agent_instructions.render import (
    USER_GLOBAL_FILE,
    render_workspace_instruction_set,
)


def find_project_root(cwd: str, markers: List[str], file_system: Any = None, signal: Any = None) -> str:
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


def ancestor_chain(root: str, cwd: str) -> List[str]:
    chain: List[str] = []
    current = os.path.abspath(cwd)
    resolved_root = os.path.abspath(root)
    while current != resolved_root:
        chain.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    chain.append(resolved_root)
    chain.reverse()
    return chain


def descendant_dirs_between(root: str, touched_path: str) -> List[str]:
    resolved_root = os.path.abspath(root)
    target_path = os.path.abspath(touched_path) if os.path.isabs(touched_path) else os.path.abspath(os.path.join(resolved_root, touched_path))
    target_dir = os.path.dirname(target_path)
    try:
        rel = os.path.relpath(target_dir, resolved_root)
    except ValueError:
        return []
    if not rel or rel.startswith("..") or os.path.isabs(rel):
        return []
    chain = ancestor_chain(resolved_root, target_dir)
    return chain[1:]


def relative_display(root: str, path: str) -> str:
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


def dsh_home_display(dsh_home: str) -> str:
    user_home = os.path.expanduser("~")
    if dsh_home == os.path.join(user_home, ".dsh"):
        return "~/.dsh"
    return dsh_home.replace("\\", "/")


def user_global_display_path(dsh_home: str) -> str:
    return f"{dsh_home_display(dsh_home)}/{USER_GLOBAL_FILE}"


def dedup_instruction_files_by_directory(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept_digests_by_dir: Dict[str, Set[str]] = {}
    kept: List[Dict[str, Any]] = []
    for file_item in files:
        directory = os.path.dirname(file_item["displayPath"])
        digests = kept_digests_by_dir.setdefault(directory, set())
        digest = trimmed_instruction_digest(file_item["content"])
        if digest in digests:
            continue
        digests.add(digest)
        kept.append(file_item)
    return kept


def discover_instruction_files(options: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfg = resolve_discovery_config(options)
    cwd = os.path.abspath(options.get("cwd", os.getcwd()))
    project_root = options.get("projectRoot") or find_project_root(cwd, cfg.project_root_markers)

    files: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def add_file(abs_path: str, disp_path: str) -> None:
        real_key = os.path.normcase(os.path.abspath(abs_path))
        if real_key in seen:
            return
        seen.add(real_key)
        files.append({"absolutePath": abs_path, "displayPath": disp_path})

    # Check user-global file
    user_global = os.path.join(cfg.dsh_home, USER_GLOBAL_FILE)
    if os.path.isfile(user_global):
        add_file(user_global, user_global_display_path(cfg.dsh_home))

    # Check root-to-cwd directory chain
    for d in ancestor_chain(project_root, cwd):
        for candidate_list in [cfg.instruction_file_candidates, cfg.local_instruction_file_candidates]:
            for candidate in candidate_list:
                file_path = os.path.join(d, candidate)
                if os.path.isfile(file_path):
                    disp = relative_display(project_root, file_path)
                    add_file(file_path, disp)

    return files


def discover_baseline_instruction_files(options: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {"absolutePath": f["absolutePath"], "displayPath": f["displayPath"]}
        for f in discover_instruction_files(options)
    ]


def read_bounded(abs_path: str, max_source_bytes: int) -> Optional[str]:
    if not os.path.isfile(abs_path):
        return None
    try:
        if os.path.getsize(abs_path) > max_source_bytes:
            return None
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if len(content.encode("utf-8")) > max_source_bytes:
            return None
        return content
    except Exception:
        return None


def load_baseline_instruction_set(options: Dict[str, Any], file_system: Any = None) -> Optional[Dict[str, Any]]:
    cfg = resolve_config(options)
    if cfg.max_bytes <= 0 or cfg.max_source_bytes <= 0:
        return None

    discovered = discover_instruction_files(options)
    loaded: List[Dict[str, Any]] = []
    for f in discovered:
        content = read_bounded(f["absolutePath"], cfg.max_source_bytes)
        if content is not None:
            loaded.append({
                "absolutePath": f["absolutePath"],
                "displayPath": f["displayPath"],
                "content": content,
            })

    deduped = dedup_instruction_files_by_directory(loaded)
    if not deduped:
        if options.get("replacePreviousBaseline") is not True:
            return None
        res = render_workspace_instruction_set([], {"maxBytes": cfg.max_bytes, "replacePreviousBaseline": True})
        return {"rendered": res["rendered"], "observed": [], "included": res["included"]}

    res = render_workspace_instruction_set(deduped, {
        "maxBytes": cfg.max_bytes,
        "replacePreviousBaseline": options.get("replacePreviousBaseline"),
    })
    return {"rendered": res["rendered"], "observed": loaded, "included": res["included"]}


def discover_and_read_files(work_dir: str, candidates: List[str], max_bytes: int) -> List[Dict[str, str]]:
    """Legacy helper maintained for backward compatibility with existing tests."""
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
                    results.append({"path": name, "content": content, "full_path": file_path, "displayPath": name})
                    break

                total_bytes += len(encoded)
                results.append({"path": name, "content": content, "full_path": file_path, "displayPath": name})
            except Exception:
                pass

    return results
