from collections.abc import Mapping
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


WEB_SEARCH_MAX_RESULTS = 8
WEB_SEARCH_MAX_QUERIES = 4


def parse_search_args(args: Dict[str, Any], max_queries: int) -> List[str]:
    queries = args["queries"]
    if len(queries) == 0:
        raise ValueError("queries must contain at least one query")
    if len(queries) > max_queries:
        noun = "query" if max_queries == 1 else "queries"
        raise ValueError("queries must contain at most %d %s" % (max_queries, noun))
    if any(query.strip() == "" for query in queries):
        raise ValueError("each query must be a non-empty string")
    unique = []
    seen = set()
    for query in queries:
        if query not in seen:
            seen.add(query)
            unique.append(query)
    return unique


def source_label(url: str, title: Optional[str] = None) -> str:
    if title is not None and len(title) > 0:
        return title
    try:
        return urlparse(url).hostname or url
    except Exception:
        return url


def format_search_output(result: Any, content: Optional[str] = None,
                         truncated: bool = False) -> str:
    if isinstance(result, list):
        value = {"sources": result, "truncated": truncated}
        if content is not None:
            value["content"] = content
    else:
        value = result
    parts = []
    answer = value.get("content")
    sources = value["sources"]
    if answer is not None and len(answer) > 0:
        parts.append(answer)
    if sources:
        lines = []
        for source in sources:
            url = source["url"]
            meta = []
            snippet = source.get("snippet")
            published = source.get("publishedAt")
            if snippet is not None and len(snippet) > 0:
                meta.append(snippet)
            if published is not None and len(published) > 0:
                meta.append("(%s)" % published)
            suffix = " \u2014 " + " ".join(meta) if meta else ""
            lines.append("- [%s](%s)%s" % (source_label(url, source.get("title")), url, suffix))
        parts.append("Sources:\n" + "\n".join(lines))
    elif answer is None or len(answer) == 0:
        parts.append("No results found.")
    if value["truncated"]:
        parts.append("(Showing the first %d sources. Refine the query for more.)" % len(sources))
    parts.append("Cite the relevant URLs above as markdown links in your answer.")
    return "\n\n".join(parts)


def project_source(source: Mapping) -> Dict[str, Any]:
    result = {"url": source["url"]}
    for name in ("title", "snippet", "publishedAt"):
        if source.get(name) is not None:
            result[name] = source[name]
    return result


def search_meta_from_value(value: Mapping) -> Dict[str, Any]:
    result = {"sources": [project_source(source) for source in value["sources"]],
              "truncated": value["truncated"]}
    if value.get("content") is not None:
        result["answer"] = value["content"]
    return result


def search_meta_from_result(meta: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(meta, Mapping):
        return None
    sources = meta.get("sources")
    if not isinstance(sources, (list, tuple)) or not isinstance(meta.get("truncated"), bool):
        return None
    answer = meta.get("answer")
    if answer is not None and not isinstance(answer, str):
        return None
    projected = []
    for source in sources:
        if not isinstance(source, Mapping) or not isinstance(source.get("url"), str):
            return None
        for name in ("title", "snippet", "publishedAt"):
            if source.get(name) is not None and not isinstance(source[name], str):
                return None
        projected.append(project_source(source))
    result = {"sources": projected, "truncated": meta["truncated"]}
    if answer is not None:
        result["answer"] = answer
    return result


def present_search_call(args: Dict[str, Any]) -> Dict[str, Any]:
    title = ", ".join(args["queries"])
    return {"card": "generic", "title": title, "kind": "search", "rawInput": title}


def present_search_result(args: Dict[str, Any], result: Any) -> Any:
    if getattr(result, "is_error", getattr(result, "isError", False)):
        return None
    meta = search_meta_from_result(getattr(result, "meta", None))
    if meta is None:
        return None
    view = {"card": "web", "kind": "search", "title": ", ".join(args["queries"]),
            "sources": meta["sources"], "truncated": meta["truncated"]}
    if meta.get("answer") is not None:
        view["answer"] = meta["answer"]
    return view
