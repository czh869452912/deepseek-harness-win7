"""File discovery and content search tools (`@deepseek-ai/dsh-tool-fs-search`)."""

import inspect
from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin
from dsh.fs.tool_fs_search.glob import (
    GLOB_MAX_RESULTS,
    build_glob_command,
    glob_card_page,
    parse_glob_args,
    present_glob_call,
    present_glob_result,
    render_glob_paths,
    sample_across_top_level,
)
from dsh.fs.tool_fs_search.grep import (
    GREP_MAX_LINE_BYTES,
    GREP_MAX_MATCHES,
    build_grep_command,
    format_grep_matches,
    parse_grep_args,
    parse_grep_matches,
    present_grep_call,
    present_grep_result,
    render_retained_grep,
    validate_include,
)
from dsh.fs.tool_fs_search.search_core import (
    RAW_OUTPUT_MAX_BYTES,
    SEARCH_GRACE_MS,
    SEARCH_META_MAX_BYTES,
    SEARCH_STDERR_MAX_BYTES,
    SEARCH_TIMEOUT_MS,
    SearchError,
    cap_meta_bytes,
    retain_grep_matches,
    run_ripgrep,
    to_workdir_relative,
)


def _positive_integer(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("tool-fs-search: %s must be a positive integer" % name)
    return value


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class FsSearchService:
    """Compatibility surface plus canonical acquisition used by the plugin."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = dict(config or {})
        if "sampleOverCapGlobResults" not in cfg:
            raise ValueError("tool-fs-search: sampleOverCapGlobResults is required")
        if not isinstance(cfg["sampleOverCapGlobResults"], bool):
            raise ValueError("tool-fs-search: sampleOverCapGlobResults must be a boolean")
        self.sample_over_cap_glob = cfg["sampleOverCapGlobResults"]
        self.glob_max_results = _positive_integer("globMaxResults", cfg.get("globMaxResults", GLOB_MAX_RESULTS))
        self.grep_max_matches = _positive_integer("grepMaxMatches", cfg.get("grepMaxMatches", GREP_MAX_MATCHES))
        self.grep_max_line_bytes = _positive_integer("grepMaxLineBytes", cfg.get("grepMaxLineBytes", GREP_MAX_LINE_BYTES))
        self.search_meta_max_bytes = _positive_integer("searchMetaMaxBytes", cfg.get("searchMetaMaxBytes", SEARCH_META_MAX_BYTES))
        self.raw_output_max_bytes = _positive_integer("rawOutputMaxBytes", cfg.get("rawOutputMaxBytes", RAW_OUTPUT_MAX_BYTES))
        self.grace_ms = _positive_integer("graceMs", cfg.get("graceMs", SEARCH_GRACE_MS))
        if self.grace_ms > 2_147_483_647:
            raise ValueError("tool-fs-search: graceMs must be no greater than 2147483647")
        self.stderr_max_bytes = _positive_integer("stderrMaxBytes", cfg.get("stderrMaxBytes", SEARCH_STDERR_MAX_BYTES))
        self.timeout_ms = _positive_integer("timeoutMs", cfg.get("timeoutMs", SEARCH_TIMEOUT_MS))

    async def acquire_glob(self, args: Dict[str, Any], exec_context: Any, ctx: Any) -> Dict[str, Any]:
        parsed = parse_glob_args(args)
        run = await run_ripgrep(
            ctx, exec_context, "glob", build_glob_command(parsed),
            self.raw_output_max_bytes, self.grace_ms, self.stderr_max_bytes,
        )
        root_display = "." if parsed.get("path") is None else to_workdir_relative(
            parsed["path"], run["workdir"])
        if run["noMatches"]:
            return {"root": root_display, "paths": []}
        paths = [to_workdir_relative(line, run["workdir"])
                 for line in run["stdout"].split("\n") if line]
        return {"root": root_display, "paths": paths}

    async def acquire_grep(self, args: Dict[str, Any], exec_context: Any, ctx: Any) -> Dict[str, Any]:
        parsed = parse_grep_args(args)
        run = await run_ripgrep(
            ctx, exec_context, "grep", build_grep_command(parsed),
            self.raw_output_max_bytes, self.grace_ms, self.stderr_max_bytes,
        )
        if run["noMatches"]:
            return {"matches": []}
        matches = parse_grep_matches(run["stdout"])
        for match in matches:
            match["path"] = to_workdir_relative(match["path"], run["workdir"])
        return {"matches": matches}

class ToolFsSearchPlugin(Plugin):
    id = "tool-fs-search"
    name = "@deepseek-ai/dsh-tool-fs-search"
    inject = ["tools", "systemPrompt", "subprocess"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.service = FsSearchService(config)

    def apply(self, ctx: Any) -> None:
        service = self.service

        def setup() -> Any:
            # Cordis inject properties are caller-bound traceable proxies.  Using
            # raw ctx.get() here registers onto the root tools catalog and loses
            # this plugin Fiber's scope (the TS plugin uses ctx.tools etc.).
            tools = ctx.tools
            prompt = ctx.systemPrompt
            disposers = []
            over_cap_guidance = (
                "while a larger one is sampled across top-level entries, so it spans the tree instead of one subtree."
                if service.sample_over_cap_glob else
                "while a larger one keeps the modification-time-ordered head."
            )
            disposers.append(prompt.section({
                "name": "tool:glob", "order": 103,
                "text": ('Use the glob tool \u2014 not shell find \u2014 to discover files by path pattern. A pattern with no "/" matches basenames at any depth, so "*" matches every file in the tree rather than its top level. '
                         'Results are files only, never directories, and include hidden and ignored files: a result that fits comes back in modification-time order, %s' % over_cap_guidance),
            }))
            disposers.append(prompt.section({
                "name": "tool:grep", "order": 104,
                "text": "Use the grep tool \u2014 not shell grep or rg \u2014 to search file contents. Use read on a matched file when you need surrounding context.",
            }))

            async def execute_glob(args: Dict[str, Any], exec_context: Any) -> Dict[str, Any]:
                return await service.acquire_glob(args, exec_context, ctx)

            async def execute_grep(args: Dict[str, Any], exec_context: Any) -> Dict[str, Any]:
                return await service.acquire_grep(args, exec_context, ctx)

            over_cap_description = (
                "a larger result instead returns %d paths sampled across top-level entries" % service.glob_max_results
                if service.sample_over_cap_glob else
                "a larger result returns the first %d paths in modification-time order" % service.glob_max_results
            )
            glob_definition = {
                "name": "glob",
                "description": ("Find files whose paths match a glob pattern. Returns matching file paths \u2014 never directories \u2014 "
                                "including hidden and ignored files (VCS metadata directories are excluded). "
                                "Up to %d paths come back in modification-time order; %s, "
                                "says so, and reports where the complete sorted list was saved. This tool does not enumerate directory entries."
                                % (service.glob_max_results, over_cap_description)),
                "parameters": {"type": "object", "additionalProperties": False, "required": ["pattern"], "properties": {
                    "pattern": {"type": "string", "description": ('Glob pattern to match file paths against (e.g. "**/*.ts", "src/**/*.test.js"). '
                                                                    'A pattern with no "/" matches the basename at any depth, so "*" and "*.ts" both search the whole tree; include a separator to anchor the depth.')},
                    "path": {"type": "string", "description": "Directory to search in. Defaults to the session workspace; a relative path resolves against it."},
                }},
                "timeoutMs": service.timeout_ms,
                "output": {
                    "schema": {"type": "object", "additionalProperties": False, "required": ["root", "paths"], "properties": {
                        "root": {"type": "string"},
                        "paths": {"type": "array", "items": {"type": "string"}},
                    }},
                    "render": lambda _args, value: [{"type": "text", "text": render_glob_paths(
                        value["paths"], service.glob_max_results, service.sample_over_cap_glob, value["root"])}],
                    "presentationMeta": lambda _args, value: cap_meta_bytes({
                        "shape": "paths",
                        "paths": glob_card_page(value["paths"], service.glob_max_results,
                                                service.sample_over_cap_glob, value["root"])["items"],
                        "truncated": len(value["paths"]) > service.glob_max_results,
                        "total": len(value["paths"]),
                    }, service.search_meta_max_bytes),
                },
                "execute": execute_glob, "presentCall": present_glob_call, "presentResult": present_glob_result,
            }
            grep_definition = {
                "name": "grep",
                "description": "Search file contents with a ripgrep regular expression. Returns matching lines with line numbers, grouped by file. Returns the first %d matches inline." % service.grep_max_matches,
                "parameters": {"type": "object", "additionalProperties": False, "required": ["pattern"], "properties": {
                    "pattern": {"type": "string", "description": "Regular expression to search for (ripgrep syntax)."},
                    "path": {"type": "string", "description": "File or directory to search. Defaults to the session workspace; a relative path resolves against it."},
                    "include": {"type": "string", "description": "One positive glob filter for files to search."},
                }},
                "timeoutMs": service.timeout_ms,
                "output": {
                    "schema": {"type": "object", "additionalProperties": False, "required": ["matches"], "properties": {
                        "matches": {"type": "array", "items": {
                            "type": "object", "additionalProperties": False, "required": ["path", "lineNumber", "line"], "properties": {
                                "path": {"type": "string"},
                                "lineNumber": {"type": "integer"},
                                "line": {"type": "string"},
                            }},
                        },
                    }},
                    "render": lambda _args, value: [{"type": "text", "text": render_retained_grep(
                        retain_grep_matches(value["matches"], service.grep_max_matches,
                                            service.grep_max_line_bytes))}],
                    "presentationMeta": lambda _args, value: _grep_meta(value, service),
                },
                "execute": execute_grep, "presentCall": present_grep_call, "presentResult": present_grep_result,
            }
            disposers.append(tools.register(glob_definition))
            glob_tool = tools.get("glob", ctx)
            disposers.append(tools.register(grep_definition))
            grep_tool = tools.get("grep", ctx)

            async def post_glob(exec_context: Any, result: Any, next_fn: Any) -> Dict[str, Any]:
                decision = await next_fn()
                if not _direct_value_is_accepted(
                        ctx, glob_tool, decision, exec_context, result, "glob"):
                    return decision
                value = result.value
                if len(value["paths"]) <= service.glob_max_results:
                    return decision
                spill_ref = await _try_save(ctx, exec_context, "glob-results.txt", "\n".join(value["paths"]))
                replacement = {"kind": "accept", "content": [{"type": "text", "text": render_glob_paths(
                    value["paths"], service.glob_max_results, service.sample_over_cap_glob,
                    value["root"], spill_ref)}]}
                if decision.get("additionalContexts") is not None:
                    replacement["additionalContexts"] = decision["additionalContexts"]
                return replacement

            async def post_grep(exec_context: Any, result: Any, next_fn: Any) -> Dict[str, Any]:
                decision = await next_fn()
                if not _direct_value_is_accepted(
                        ctx, grep_tool, decision, exec_context, result, "grep"):
                    return decision
                value = result.value
                if len(value["matches"]) <= service.grep_max_matches:
                    return decision
                previewed = retain_grep_matches(value["matches"], len(value["matches"]),
                                                service.grep_max_line_bytes)["items"]
                complete = "Found %d matches\n\n%s" % (len(previewed), format_grep_matches(previewed))
                spill_ref = await _try_save(ctx, exec_context, "grep-results.txt", complete)
                replacement = {"kind": "accept", "content": [{"type": "text", "text": render_retained_grep(
                    retain_grep_matches(value["matches"], service.grep_max_matches,
                                        service.grep_max_line_bytes), spill_ref)}]}
                if decision.get("additionalContexts") is not None:
                    replacement["additionalContexts"] = decision["additionalContexts"]
                return replacement

            ctx.on("tools/post-execute", post_glob)
            ctx.on("tools/post-execute", post_grep)

            def cleanup() -> None:
                for disposer in reversed(disposers):
                    if callable(disposer):
                        disposer()

            return cleanup

        ctx.effect(setup, label="tool-fs-search")


def _grep_meta(value: Dict[str, Any], service: FsSearchService) -> Dict[str, Any]:
    retained = retain_grep_matches(value["matches"], service.grep_max_matches, service.grep_max_line_bytes)
    grouped = {}
    order = []
    for match in retained["items"]:
        if match["path"] not in grouped:
            grouped[match["path"]] = []
            order.append(match["path"])
        grouped[match["path"]].append({"lineNumber": match["lineNumber"], "line": match["line"]})
    return cap_meta_bytes({"shape": "matches",
                           "files": [{"path": path, "matches": grouped[path]} for path in order],
                           "truncated": retained["truncated"], "total": retained["seen"]},
                          service.search_meta_max_bytes)


def _direct_value_is_accepted(ctx: Any, tool: Any, decision: Any,
                              exec_context: Any, result: Any, name: str) -> bool:
    tools = ctx.tools
    return (isinstance(decision, dict) and decision.get("kind") == "accept"
            and "content" not in decision and "value" not in decision
            and getattr(exec_context, "parent", None) is None
            and getattr(exec_context, "name", None) == name
            and not getattr(result, "is_error", False)
            and tools.get(name, getattr(exec_context, "agent", None)) is tool)


async def _try_save(ctx: Any, exec_context: Any, suggested_name: str,
                    content: str) -> Any:
    agent = getattr(exec_context, "agent", None)
    header = getattr(getattr(agent, "session", None), "header", None)
    session_id = header.get("id") if isinstance(header, dict) else getattr(header, "id", None)
    if session_id is None:
        return None
    try:
        store = ctx.get("spillStore", None, strict=False)
    except TypeError:
        store = ctx.get("spillStore")
    if store is None:
        return None
    saver = getattr(store, "saveText", None) or getattr(store, "save_text", None)
    if not callable(saver):
        return None
    try:
        value = saver({"owner": {"sessionId": session_id},
                       "source": {"toolName": exec_context.name, "callId": exec_context.call_id},
                       "suggestedName": suggested_name, "content": content})
        return await _maybe_await(value)
    except Exception:
        return None


__all__ = [
    "FsSearchService", "ToolFsSearchPlugin", "SearchError", "sample_across_top_level",
    "parse_glob_args", "parse_grep_args", "present_glob_call", "present_grep_call",
    "format_grep_matches", "validate_include",
]
