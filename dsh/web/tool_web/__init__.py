"""Canonical model-facing web tools over the injected web service."""

import asyncio
import inspect
from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin
from dsh.llm.error import HarnessError
from dsh.web.tool_web.fetch import (
    fetch_meta_from_value,
    format_fetch_output,
    parse_fetch_args,
    present_fetch_call,
    present_fetch_result,
)
from dsh.web.tool_web.search import (
    WEB_SEARCH_MAX_QUERIES,
    WEB_SEARCH_MAX_RESULTS,
    format_search_output,
    parse_search_args,
    present_search_call,
    present_search_result,
    project_source,
    search_meta_from_value,
)
from dsh.web.web_service import WebService


DEFAULT_WEB_TOOL_TIMEOUT_MS = 30_000
DEFAULT_FETCH_MAX_OUTPUT_CHARS = 200_000


class WebToolError(HarnessError):
    pass


def _positive_integer(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("tool-web: %s must be a positive integer" % name)
    return value


def _boolean(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("tool-web: %s must be a boolean" % name)
    return value


def _legacy_provider_available(web: WebService, kind: str) -> bool:
    selected = web.default_search if kind == "search" else web.default_fetch
    providers = web.search_providers if kind == "search" else web.fetch_providers
    return selected is not None and selected in providers


class _BatchSignal:
    def __init__(self, caller: Any):
        self.caller = caller
        self.internal = asyncio.Event()

    def is_set(self) -> bool:
        checker = getattr(self.caller, "is_set", None)
        return self.internal.is_set() or (bool(checker()) if callable(checker) else bool(getattr(self.caller, "aborted", False)))

    @property
    def aborted(self) -> bool:
        return self.is_set()

    def abort(self) -> None:
        self.internal.set()

    async def wait(self) -> None:
        if self.is_set():
            return
        tasks = [asyncio.ensure_future(self.internal.wait())]
        caller_wait = getattr(self.caller, "wait", None)
        if callable(caller_wait):
            pending = caller_wait()
            if inspect.isawaitable(pending):
                tasks.append(asyncio.ensure_future(pending))
        listener_future = None
        add_listener = getattr(self.caller, "addEventListener", None)
        remove_listener = getattr(self.caller, "removeEventListener", None)
        wake = None
        if callable(add_listener):
            listener_future = asyncio.get_running_loop().create_future()

            def wake(*_args: Any) -> None:
                if not listener_future.done():
                    listener_future.set_result(None)

            add_listener("abort", wake)
            tasks.append(listener_future)
        try:
            done, pending_tasks = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending_tasks:
                task.cancel()
            for task in done:
                task.result()
        finally:
            if wake is not None and callable(remove_listener):
                remove_listener("abort", wake)


def _normalize_source(source: Mapping) -> Dict[str, Any]:
    normalized = {"url": source.get("url", "")}
    for target, alternatives in (
            ("title", ("title",)), ("snippet", ("snippet",)),
            ("publishedAt", ("publishedAt", "published_at"))):
        for name in alternatives:
            if source.get(name) is not None:
                normalized[target] = source[name]
                break
    return normalized


def _normalize_search_result(value: Any, max_results: int,
                             legacy: bool) -> Dict[str, Any]:
    if isinstance(value, list):
        sources = [_normalize_source(source) for source in value]
        return {"sources": sources[:max_results], "truncated": len(sources) > max_results}
    if not isinstance(value, Mapping):
        raise TypeError("web search provider returned an invalid result")
    raw_sources = value.get("sources", [])
    sources = [_normalize_source(source) for source in raw_sources]
    result = {"sources": sources, "truncated": bool(value.get("truncated", False))}
    if legacy and len(sources) > max_results:
        result["sources"] = sources[:max_results]
        result["truncated"] = True
    if value.get("content") is not None:
        result["content"] = value["content"]
    return result


def _accepts_signal(method: Any) -> bool:
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False
    return ("signal" in parameters
            or any(parameter.kind == inspect.Parameter.VAR_KEYWORD
                   for parameter in parameters.values()))


async def _call_search(web: Any, query: str, max_results: int, signal: Any) -> Dict[str, Any]:
    try:
        if isinstance(web, WebService):
            if not _legacy_provider_available(web, "search"):
                raise WebToolError("No active web search provider registered", "WEB_PROVIDER_UNAVAILABLE")
            kwargs = {"max_results": max_results}
            if _accepts_signal(web.search):
                kwargs["signal"] = signal
            value = await web.search(query, **kwargs)
            return _normalize_search_result(value, max_results, True)
        value = await web.search({"query": query, "maxResults": max_results}, signal)
        return _normalize_search_result(value, max_results, False)
    except Exception as error:
        if isinstance(web, WebService) and not _legacy_provider_available(web, "search"):
            raise WebToolError("No active web search provider registered", "WEB_PROVIDER_UNAVAILABLE")
        raise


def _normalize_fetch_result(value: Any, requested_url: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("web fetch provider returned an invalid result")
    if isinstance(value.get("body"), Mapping):
        body = value["body"]
        kind = body.get("kind")
        content = body.get("content")
    else:
        kind = "text"
        content = value.get("content", "")
    return {
        "url": value.get("url", requested_url),
        "statusCode": value.get("statusCode", value.get("status", 200)),
        "body": {"kind": kind, "content": content},
        "truncated": bool(value.get("truncated", False)),
    }


async def _call_fetch(web: Any, url: str, signal: Any) -> Dict[str, Any]:
    try:
        if isinstance(web, WebService):
            if not _legacy_provider_available(web, "fetch"):
                raise WebToolError("No active web fetch provider registered", "WEB_PROVIDER_UNAVAILABLE")
            kwargs = {"signal": signal} if _accepts_signal(web.fetch) else {}
            value = await web.fetch(url, **kwargs)
        else:
            value = await web.fetch({"url": url}, signal)
        return _normalize_fetch_result(value, url)
    except Exception as error:
        if isinstance(web, WebService) and not _legacy_provider_available(web, "fetch"):
            raise WebToolError("No active web fetch provider registered", "WEB_PROVIDER_UNAVAILABLE")
        raise


def _merge_search_results(queries: List[str], results: List[Dict[str, Any]],
                          max_results: int) -> Dict[str, Any]:
    seen = set()
    sources = []
    ranks = max([len(result["sources"]) for result in results] or [0])
    dropped = False
    for rank in range(ranks):
        stop = False
        for result in results:
            if rank >= len(result["sources"]):
                continue
            source = result["sources"][rank]
            if source["url"] in seen:
                continue
            seen.add(source["url"])
            if len(sources) == max_results:
                dropped = True
                stop = True
                break
            sources.append(source)
        if stop:
            break
    contents = []
    for index, result in enumerate(results):
        if result.get("content"):
            contents.append("### %s\n\n%s" % (queries[index], result["content"]))
    merged = {"sources": sources,
              "truncated": any(result["truncated"] for result in results) or dropped}
    if contents:
        merged["content"] = "\n\n".join(contents)
    return merged


async def _run_search_queries(web: Any, queries: List[str], max_results: int,
                              caller_signal: Any) -> Dict[str, Any]:
    if len(queries) == 1:
        return await _call_search(web, queries[0], max_results, caller_signal)
    batch_signal = _BatchSignal(caller_signal)
    results = [None] * len(queries)
    first_failure = []

    async def search_one(index: int, query: str) -> None:
        try:
            results[index] = await _call_search(web, query, max_results, batch_signal)
        except Exception as error:
            if not first_failure:
                first_failure.append(error)
            batch_signal.abort()

    await asyncio.gather(*[search_one(index, query) for index, query in enumerate(queries)])
    if first_failure:
        raise first_failure[0]
    return _merge_search_results(queries, results, max_results)


class ToolWebPlugin(Plugin):
    id = "tool-web"
    name = "tool-web"
    inject = ["tools", "web", "systemPrompt"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = dict(config or {})
        self.enable_search = _boolean("search", cfg.get("search", True))
        self.enable_fetch = _boolean("fetch", cfg.get("fetch", True))
        self.max_results = _positive_integer("searchMaxResults", cfg.get("searchMaxResults", WEB_SEARCH_MAX_RESULTS))
        self.max_queries = _positive_integer("searchMaxQueries", cfg.get("searchMaxQueries", WEB_SEARCH_MAX_QUERIES))
        self.fetch_timeout_ms = _positive_integer("fetchTimeoutMs", cfg.get("fetchTimeoutMs", DEFAULT_WEB_TOOL_TIMEOUT_MS))
        self.search_timeout_ms = _positive_integer("searchTimeoutMs", cfg.get("searchTimeoutMs", DEFAULT_WEB_TOOL_TIMEOUT_MS))
        self.max_output_chars = _positive_integer("fetchMaxOutputChars", cfg.get("fetchMaxOutputChars", DEFAULT_FETCH_MAX_OUTPUT_CHARS))

    def apply(self, ctx: Any) -> None:
        def setup() -> Any:
            tools = ctx.get("tools")
            web = ctx.get("web")
            prompt = ctx.get("systemPrompt")
            disposers = []
            if self.enable_search:
                follow_up = ("Follow up with web_fetch when you need the full content of a specific result, and cite the relevant URLs as markdown links."
                             if self.enable_fetch else
                             "Use the returned source snippets when available, and cite the relevant URLs as markdown links.")
                disposers.append(prompt.section({
                    "name": "tool:web_search", "order": 110,
                    "text": "Use the web_search tool to discover current information on the web. The required queries array accepts 1\u2013%d non-empty search queries; use a one-item array for a single search. It returns an optional answer plus a list of source URLs. %s" %
                            (self.max_queries, follow_up),
                }))

                async def execute_search(args: Dict[str, Any], exec_context: Any) -> Dict[str, Any]:
                    queries = parse_search_args(args, self.max_queries)
                    value = await _run_search_queries(web, queries, self.max_results, exec_context.signal)
                    result = {"sources": [project_source(source) for source in value["sources"]],
                              "truncated": value["truncated"]}
                    if value.get("content") is not None:
                        result["content"] = value["content"]
                    return result

                disposers.append(tools.register({
                    "name": "web_search",
                    "description": "Search the web for current information. Provide 1\u2013%d queries in the required queries array. Returns an optional summary answer and a list of source URLs." % self.max_queries,
                    "parameters": {"type": "object", "additionalProperties": False,
                                   "required": ["queries"], "properties": {
                        "queries": {"type": "array", "items": {"type": "string"},
                                    "description": "Required search queries; accepts 1\u2013%d items and merges their results." % self.max_queries},
                    }},
                    "output": {"schema": _search_output_schema(),
                               "render": lambda _args, value: [{"type": "text", "text": format_search_output(value)}],
                               "presentationMeta": lambda _args, value: search_meta_from_value(value)},
                    "timeoutMs": self.search_timeout_ms,
                    "isConcurrencySafe": lambda _args: True,
                    "execute": execute_search,
                    "presentCall": present_search_call,
                    "presentResult": present_search_result,
                }))
            if self.enable_fetch:
                disposers.append(prompt.section({
                    "name": "tool:web_fetch", "order": 111,
                    "text": "Use the web_fetch tool to retrieve the content of a specific HTTP(S) URL (for example a result from web_search). It returns the page content decoded to text. Cite the URL as a markdown link when you use its content.",
                }))

                async def execute_fetch(args: Dict[str, Any], exec_context: Any) -> Dict[str, Any]:
                    parsed = parse_fetch_args(args)
                    return await _call_fetch(web, parsed["url"], exec_context.signal)

                disposers.append(tools.register({
                    "name": "web_fetch",
                    "description": "Fetch the content of a specific HTTP(S) URL and return it decoded to text.",
                    "parameters": {"type": "object", "additionalProperties": False,
                                   "required": ["url"], "properties": {
                        "url": {"type": "string", "description": "The HTTP(S) URL to fetch."},
                    }},
                    "output": {"schema": _fetch_output_schema(),
                               "render": lambda _args, value: [{"type": "text", "text": format_fetch_output(value, self.max_output_chars)}],
                               "presentationMeta": lambda _args, value: fetch_meta_from_value(value, self.max_output_chars)},
                    "timeoutMs": self.fetch_timeout_ms,
                    "isConcurrencySafe": lambda _args: True,
                    "execute": execute_fetch,
                    "presentCall": present_fetch_call,
                    "presentResult": present_fetch_result,
                }))

            def cleanup() -> None:
                for disposer in reversed(disposers):
                    if callable(disposer):
                        disposer()

            return cleanup

        ctx.effect(setup, label="tool-web")


def _source_schema() -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["url"], "properties": {
        "url": {"type": "string"}, "title": {"type": "string"},
        "snippet": {"type": "string"}, "publishedAt": {"type": "string"},
    }}


def _search_output_schema() -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": ["sources", "truncated"], "properties": {
        "content": {"type": "string"},
        "sources": {"type": "array", "items": _source_schema()},
        "truncated": {"type": "boolean"},
    }}


def _body_schema(kind: str) -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": ["kind", "content"], "properties": {
        "kind": {"type": "string", "const": kind}, "content": {"type": "string"},
    }}


def _fetch_output_schema() -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": ["url", "statusCode", "body", "truncated"], "properties": {
        "url": {"type": "string"}, "statusCode": {"type": "integer"},
        "body": {"oneOf": [_body_schema("html"), _body_schema("text")]},
        "truncated": {"type": "boolean"},
    }}


__all__ = ["ToolWebPlugin", "WebToolError", "DEFAULT_WEB_TOOL_TIMEOUT_MS",
           "DEFAULT_FETCH_MAX_OUTPUT_CHARS", "WEB_SEARCH_MAX_RESULTS", "WEB_SEARCH_MAX_QUERIES"]
