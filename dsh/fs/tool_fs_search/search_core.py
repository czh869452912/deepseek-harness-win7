import json
import os
import platform
import shutil
import sys
from typing import Any, Dict, List, Optional

from dsh.llm.error import HarnessError
from dsh.subprocess import SubprocessCollect, SubprocessSpawnSpec, SubprocessStdio

RAW_OUTPUT_MAX_BYTES = 20_000_000
SEARCH_TIMEOUT_MS = 30_000
SEARCH_STDERR_MAX_BYTES = 64 * 1024
SEARCH_GRACE_MS = 3_000
SEARCH_META_MAX_BYTES = 65_536
GLOB_VCS_EXCLUDES = (".git", ".svn", ".hg", ".bzr", ".jj", ".sl")
EXCLUDED_DIRS = set(GLOB_VCS_EXCLUDES)


class SearchError(HarnessError):
    pass


_rg_path_cache: Optional[str] = None


def _ripgrep_package_name() -> Optional[str]:
    systems = {"win32": "win32", "linux": "linux", "darwin": "darwin"}
    system = systems.get(sys.platform)
    machine = platform.machine().lower()
    arches = {
        "amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64",
        "x86": "ia32", "i386": "ia32", "i686": "ia32",
    }
    arch = arches.get(machine)
    return "ripgrep-%s-%s" % (system, arch) if system and arch else None


async def resolve_rg_path() -> str:
    global _rg_path_cache
    if _rg_path_cache is not None:
        return _rg_path_cache

    explicit = os.environ.get("DSH_RG_PATH")
    if explicit:
        _rg_path_cache = os.path.abspath(explicit)
        return _rg_path_cache

    binary = "rg.exe" if sys.platform == "win32" else "rg"
    package_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(package_dir, "..", "..", ".."))
    candidates = [
        sys.executable + "-rg",
        os.path.join(package_dir, "bin", binary),
    ]
    package_name = _ripgrep_package_name()
    if package_name is not None:
        candidates.append(os.path.join(
            repo_root, "reference", "deepseek-harness", "node_modules", "@vscode",
            package_name, "bin", binary,
        ))
    on_path = shutil.which("rg")
    if on_path:
        candidates.append(on_path)
    for candidate in candidates:
        if os.path.isfile(candidate):
            _rg_path_cache = os.path.abspath(candidate)
            return _rg_path_cache
    raise FileNotFoundError("packaged ripgrep binary is unavailable")


def signal_aborted(signal: Any) -> bool:
    checker = getattr(signal, "is_set", None)
    return bool(checker()) if callable(checker) else bool(getattr(signal, "aborted", False))


def throw_if_aborted(signal: Any, tool_name: str) -> None:
    if signal_aborted(signal):
        raise SearchError("%s was aborted before completion (tool timeout or caller cancellation)" % tool_name,
                          "SEARCH_ABORTED")


def _read_output(reader: Any) -> Any:
    if reader is None:
        return None
    read = getattr(reader, "read_from", None) or getattr(reader, "readFrom", None)
    return read(0) if callable(read) else None


def _outcome_value(outcome: Any, camel: str, snake: str) -> Any:
    if isinstance(outcome, dict):
        return outcome.get(camel, outcome.get(snake))
    return getattr(outcome, camel, getattr(outcome, snake, None))


def _stderr_excerpt(stderr: Any) -> str:
    text = getattr(stderr, "text", "").strip()
    if not text:
        return ""
    return text + (" [stderr truncated]" if getattr(stderr, "lossy", False) else "")


def _run_failure(tool_name: str, exit_code: int, stderr: Any) -> SearchError:
    excerpt = _stderr_excerpt(stderr)
    if "regex parse error" in excerpt.lower() or "error parsing glob" in excerpt.lower():
        return SearchError("%s pattern rejected by ripgrep: %s" % (tool_name, excerpt),
                           "SEARCH_INVALID_PATTERN")
    suffix = ": " + excerpt if excerpt else ""
    return SearchError("%s search failed (exit %s)%s" % (tool_name, exit_code, suffix),
                       "SEARCH_FAILED")


async def run_ripgrep(ctx: Any, exec_context: Any, tool_name: str,
                      argv: List[str], raw_output_max_bytes: int,
                      grace_ms: int, stderr_max_bytes: int) -> Dict[str, Any]:
    throw_if_aborted(exec_context.signal, tool_name)
    workdir = workdir_from_exec(exec_context)
    try:
        rg_path = await resolve_rg_path()
        # Resolve through the caller-bound injected property so subprocess
        # intercepts/ownership follow the plugin/session context like TS.
        subprocess_service = ctx.subprocess
        spec = SubprocessSpawnSpec(
            argv=[rg_path, "--no-config"] + list(argv),
            cwd=workdir,
            stdio=SubprocessStdio(
                stdin="ignore",
                stdout=SubprocessCollect(raw_output_max_bytes),
                stderr=SubprocessCollect(stderr_max_bytes),
            ),
            grace_ms=grace_ms,
            signal=exec_context.signal,
        )
        handle = subprocess_service.spawn(spec)
    except Exception as error:
        if signal_aborted(exec_context.signal):
            raise SearchError("%s was aborted before completion (tool timeout or caller cancellation)" % tool_name,
                              "SEARCH_ABORTED") from error
        raise SearchError("%s could not start its search command (ripgrep launch failed)" % tool_name,
                          "SEARCH_FAILED") from error

    try:
        outcome = await handle.done
    except Exception as error:
        raise SearchError("%s could not start its search command (ripgrep launch failed)" % tool_name,
                          "SEARCH_FAILED") from error

    stdout = _read_output(getattr(handle.collected, "stdout", None))
    stderr = _read_output(getattr(handle.collected, "stderr", None))
    if stdout is None or stderr is None:
        raise SearchError("%s search command produced no collected output streams" % tool_name,
                          "SEARCH_FAILED")
    throw_if_aborted(exec_context.signal, tool_name)

    process_signal = _outcome_value(outcome, "signal", "signal")
    exit_code = _outcome_value(outcome, "exitCode", "exit_code")
    if process_signal is not None or exit_code is None:
        raise SearchError("%s search command was killed by signal %s" %
                          (tool_name, process_signal or "(unknown)"), "SEARCH_FAILED")
    if exit_code not in (0, 1):
        raise _run_failure(tool_name, exit_code, stderr)
    if getattr(stdout, "lossy", False):
        raise SearchError("%s produced more raw output than the subprocess seam retained within the %d-byte cap; narrow pattern, path, or include and retry" %
                          (tool_name, raw_output_max_bytes), "SEARCH_RAW_OUTPUT_OVERFLOW")
    text = getattr(stdout, "text", "")
    byte_count = len(text.encode("utf-8"))
    if byte_count > raw_output_max_bytes:
        raise SearchError("%s produced %d bytes of raw output, over the %d-byte cap; narrow pattern, path, or include and retry" %
                          (tool_name, byte_count, raw_output_max_bytes), "SEARCH_RAW_OUTPUT_OVERFLOW")
    return {"stdout": text, "noMatches": exit_code == 1, "workdir": workdir}


def workdir_from_exec(exec_context: Any, fallback: Optional[str] = None) -> str:
    agent = getattr(exec_context, "agent", None)
    header = getattr(getattr(agent, "session", None), "header", None)
    cwd = header.get("cwd") if isinstance(header, dict) else getattr(header, "cwd", None)
    return os.path.abspath(cwd or os.getcwd())


def to_workdir_relative(path: str, workdir: str) -> str:
    if not os.path.isabs(path):
        return path
    rel = os.path.relpath(path, workdir)
    if rel == ".":
        return "."
    if rel == ".." or rel.startswith(".." + os.sep):
        return path
    return rel


def preview_line(line: str, max_bytes: int) -> str:
    raw = line.encode("utf-8")
    if len(raw) <= max_bytes:
        return line
    kept = raw[:max_bytes]
    while kept:
        try:
            return kept.decode("utf-8") + " (line truncated)"
        except UnicodeDecodeError:
            kept = kept[:-1]
    return " (line truncated)"


def retain_grep_matches(matches: List[Dict[str, Any]], max_matches: int,
                        max_line_bytes: int) -> Dict[str, Any]:
    items = []
    for match in matches[:max_matches]:
        item = dict(match)
        item["line"] = preview_line(item["line"], max_line_bytes)
        items.append(item)
    return {"items": items, "kept": len(items), "seen": len(matches),
            "omitted": max(0, len(matches) - len(items)), "truncated": len(matches) > max_matches}


def _meta_bytes(meta: Dict[str, Any]) -> int:
    return len(json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def cap_meta_bytes(meta: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    if _meta_bytes(meta) <= max_bytes:
        return meta
    result = dict(meta)
    key = "files" if meta.get("shape") == "matches" else "paths"
    values = list(meta.get(key, []))
    while len(values) > 1:
        result[key] = values
        result["truncated"] = True
        if _meta_bytes(result) <= max_bytes:
            return result
        values.pop()
    result[key] = values
    result["truncated"] = True
    return result


def strip_leading_separators(path: str) -> str:
    start = 0
    while start < len(path) and path[start] in ("/", "\\"):
        start += 1
    return path[start:]


def top_level_segment(path: str) -> str:
    trimmed = strip_leading_separators(path)
    positions = [value for value in (trimmed.find("/"), trimmed.find("\\")) if value >= 0]
    return trimmed[:min(positions)] if positions else trimmed


def relative_to_search_root(path: str, root: str) -> str:
    path = path.replace("\\", "/")
    root = root.replace("\\", "/")
    if root in (".", "./"):
        return path[2:] if path.startswith("./") else path
    trimmed = root.rstrip("/")
    if not trimmed:
        return strip_leading_separators(path)
    if path == trimmed:
        return ""
    prefix = trimmed + "/"
    return path[len(prefix):] if path.startswith(prefix) else path
