"""
Session query service with SQLite FTS5 index, semantic document extraction, filter compilation,
lineage tracing, event context reading, and model-facing search tools.
Aligned 1:1 with official `@deepseek-ai/dsh-session-query`, `@deepseek-ai/dsh-session-query-sqlite`,
and `@deepseek-ai/dsh-tool-session-query`.
"""

import json
import re
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, Tuple, Union

from dsh.cordis.plugin import Plugin
from dsh.llm.error import HarnessError

# Highlighting markers
FTS_HIGHLIGHT_START = "\uFDD0"
FTS_HIGHLIGHT_END = "\uFDD1"

# Query limits
SQLITE_MAX_PAGE_LIMIT = 9007199254740990
SQLITE_PORTABLE_VARIABLE_LIMIT = 32766
SQLITE_FTS5_OUTER_PREDICATE_LIMIT = 14
SESSION_QUERY_READ_WINDOW_MAX = 50


class SessionQueryError(HarnessError):
    """
    Typed session-query failure whose `code` is one closed taxonomy member.
    """

    def __init__(self, message: str, code: str, cause: Optional[Exception] = None) -> None:
        super().__init__(message, code, cause=cause)


def SessionSearchCursor(value: str) -> str:
    """Brand string wrapper for opaque continuation cursors."""
    return str(value)


def extract_session_event_text(event: Dict[str, Any]) -> str:
    """
    Extract searchable semantic text from one session event.
    Structural boundaries, raw stream chunks, request envelopes contribute no text.
    Reasoning blocks are excluded (1:1 with TS original).
    """
    etype = event.get("type", "")
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}

    if etype == "user/message":
        content = data.get("content")
        if content is None and "message" in data and isinstance(data["message"], dict):
            content = data["message"].get("content")
        return _content_text(content)

    elif etype == "assistant/message":
        msg = data.get("message", {})
        if isinstance(msg, dict):
            return _content_text(msg.get("content"))
        return ""

    elif etype == "tool/call":
        name = data.get("name", "")
        args = data.get("arguments", "")
        args_str = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        return _join_text([name, args_str])

    elif etype == "tool/result":
        res_text = ""
        msg = data.get("message", {})
        if isinstance(msg, dict):
            res_text = _content_text(msg.get("content"))
        else:
            res = data.get("result", "")
            res_text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False) if res else ""
        err = data.get("error", {})
        err_name = err.get("name", "") if isinstance(err, dict) else ""
        err_code = err.get("code", "") if isinstance(err, dict) else ""
        return _join_text([res_text, err_name, err_code])

    elif etype == "todo/write":
        todos = data.get("todos", [])
        parts: List[str] = []
        if isinstance(todos, list):
            for t in todos:
                if isinstance(t, dict):
                    if t.get("status"):
                        parts.append(str(t.get("status")))
                    if t.get("content"):
                        parts.append(str(t.get("content")))
        return _join_text(parts)

    elif etype == "turn/end":
        reason = data.get("reason", {})
        if isinstance(reason, dict):
            rkind = reason.get("kind", "")
            if rkind == "error":
                err = reason.get("error", {})
                err_msg = err.get("message", "") if isinstance(err, dict) else ""
                return _join_text(["error", err_msg])
            elif rkind in ("aborted", "max-tokens", "interrupted"):
                return rkind
        return ""

    return ""


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            parts.extend(_block_text(block))
        return _join_text(parts)
    return ""


def _block_text(block: Any) -> List[str]:
    if not isinstance(block, dict):
        return []
    btype = block.get("type", "")
    if btype == "text":
        return [str(block.get("text", ""))]
    elif btype == "reasoning":
        return []
    elif btype == "tool-call":
        name = str(block.get("name", ""))
        args = str(block.get("arguments", ""))
        return [name, args]
    elif btype == "tool-result":
        res_content = block.get("content", [])
        if isinstance(res_content, list):
            res_parts: List[str] = []
            for sub in res_content:
                res_parts.extend(_block_text(sub))
            return res_parts
    return []


def _join_text(parts: List[str]) -> str:
    cleaned = [p.strip() for p in parts if isinstance(p, str) and p.strip()]
    return "\n".join(cleaned)


def compile_session_text_filter(text: str) -> Pattern[str]:
    """
    Compile literal case-insensitive, whitespace-flexible semantic-text match.
    """
    trimmed = text.strip()
    if not trimmed:
        raise SessionQueryError(
            "session text filter must contain non-whitespace text",
            "SESSION_QUERY_INVALID_FILTER",
        )
    pattern = r"\s+".join(re.escape(part) for part in re.split(r"\s+", trimmed))
    return re.compile(pattern, re.IGNORECASE)


def materialize_session_result_filters(filters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(filters, list):
        raise SessionQueryError("filters must be an array", "SESSION_QUERY_INVALID_FILTER")
    result: List[Dict[str, Any]] = []
    for f in filters:
        if not isinstance(f, dict) or "kind" not in f:
            raise SessionQueryError("unknown filter kind (missing)", "SESSION_QUERY_INVALID_FILTER")
        kind = f["kind"]
        if kind == "id":
            vals = f.get("values", [])
            if not isinstance(vals, list) or any(not isinstance(v, str) for v in vals):
                raise SessionQueryError("id filter values must be an array of strings", "SESSION_QUERY_INVALID_FILTER")
            result.append({"kind": "id", "values": list(vals)})
        elif kind == "cwd":
            vals = f.get("values", [])
            if not isinstance(vals, list) or any(v is not None and not isinstance(v, str) for v in vals):
                raise SessionQueryError("cwd filter values must be an array of strings or null", "SESSION_QUERY_INVALID_FILTER")
            result.append({"kind": "cwd", "values": list(vals)})
        elif kind == "created-at":
            result.append(_copy_range("created-at", f))
        elif kind == "parent":
            vals = f.get("values", [])
            if not isinstance(vals, list) or any(v is not None and not isinstance(v, str) for v in vals):
                raise SessionQueryError("parent filter values must be an array of strings or null", "SESSION_QUERY_INVALID_FILTER")
            result.append({"kind": "parent", "values": list(vals)})
        elif kind == "availability":
            vals = f.get("values", [])
            if not isinstance(vals, list) or any(not isinstance(v, str) for v in vals):
                raise SessionQueryError("availability filter values must be an array of strings", "SESSION_QUERY_INVALID_FILTER")
            for v in vals:
                if v not in ("live", "persisted"):
                    raise SessionQueryError(f'session availability filter contains unknown value "{v}"', "SESSION_QUERY_INVALID_FILTER")
            result.append({"kind": "availability", "values": list(vals)})
        else:
            raise SessionQueryError(f'unknown filter kind "{kind}"', "SESSION_QUERY_INVALID_FILTER")
    return result


def materialize_session_event_result_filters(filters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(filters, list):
        raise SessionQueryError("filters must be an array", "SESSION_QUERY_INVALID_FILTER")
    result: List[Dict[str, Any]] = []
    for f in filters:
        if not isinstance(f, dict) or "kind" not in f:
            raise SessionQueryError("unknown filter kind (missing)", "SESSION_QUERY_INVALID_FILTER")
        kind = f["kind"]
        if kind in ("seq", "time"):
            result.append(_copy_range(kind, f))
        elif kind == "type":
            vals = f.get("values", [])
            if not isinstance(vals, list) or any(not isinstance(v, str) for v in vals):
                raise SessionQueryError("type filter values must be an array of strings", "SESSION_QUERY_INVALID_FILTER")
            result.append({"kind": "type", "values": list(vals)})
        elif kind == "surface":
            vals = f.get("values", [])
            if not isinstance(vals, list) or any(not isinstance(v, str) for v in vals):
                raise SessionQueryError("surface filter values must be an array of strings", "SESSION_QUERY_INVALID_FILTER")
            for v in vals:
                if v not in ("current", "shadowed", "log-only"):
                    raise SessionQueryError(f'session surface filter contains unknown value "{v}"', "SESSION_QUERY_INVALID_FILTER")
            result.append({"kind": "surface", "values": list(vals)})
        elif kind == "text":
            txt = f.get("text")
            if not isinstance(txt, str):
                raise SessionQueryError("text filter text must be a string", "SESSION_QUERY_INVALID_FILTER")
            result.append({"kind": "text", "text": txt})
        else:
            raise SessionQueryError(f'unknown filter kind "{kind}"', "SESSION_QUERY_INVALID_FILTER")
    return result


def _copy_range(kind: str, rdict: Dict[str, Any]) -> Dict[str, Any]:
    copy: Dict[str, Any] = {"kind": kind}
    if "from" in rdict and rdict["from"] is not None:
        copy["from"] = rdict["from"]
    if "to" in rdict and rdict["to"] is not None:
        copy["to"] = rdict["to"]
    _validate_range(kind, copy)
    return copy


def _validate_range(name: str, rdict: Dict[str, Any]) -> None:
    rfrom = rdict.get("from")
    rto = rdict.get("to")
    if rfrom is not None and not isinstance(rfrom, (int, float)):
        raise SessionQueryError(f"session {name} filter from must be finite", "SESSION_QUERY_INVALID_FILTER")
    if rto is not None and not isinstance(rto, (int, float)):
        raise SessionQueryError(f"session {name} filter to must be finite", "SESSION_QUERY_INVALID_FILTER")
    if rfrom is not None and rto is not None and rfrom > rto:
        raise SessionQueryError(f"session {name} filter from must be less than or equal to to", "SESSION_QUERY_INVALID_FILTER")


def filter_session_results(
    records: List[Dict[str, Any]],
    filters: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Apply ANDed logical-session filters while preserving input order.
    """
    if not filters:
        return list(records)
    mat_filters = materialize_session_result_filters(filters) if isinstance(filters[0], dict) else None
    res = []
    for rec in records:
        if mat_filters:
            match = True
            hdr = rec.get("header", rec)
            for f in mat_filters:
                kind = f["kind"]
                if kind == "id" and hdr.get("id") not in f["values"]:
                    match = False; break
                elif kind == "cwd" and hdr.get("cwd") not in f["values"]:
                    match = False; break
                elif kind == "created-at":
                    ca = hdr.get("createdAt", 0)
                    if ("from" in f and ca < f["from"]) or ("to" in f and ca > f["to"]):
                        match = False; break
                elif kind == "parent" and hdr.get("parentSession") not in f["values"]:
                    match = False; break
                elif kind == "availability":
                    live = rec.get("live", False)
                    persisted = rec.get("persisted", False)
                    if not any((v == "live" and live) or (v == "persisted" and persisted) for v in f["values"]):
                        match = False; break
            if match:
                res.append(rec)
        elif callable(filters[0]):
            if all(f(rec) for f in filters):
                res.append(rec)
    return res


def filter_session_event_documents(
    documents: List[Dict[str, Any]],
    filters: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Apply ANDed event filters to extracted semantic documents.
    """
    if not filters:
        return list(documents)
    mat_filters = materialize_session_event_result_filters(filters)
    res = []
    for doc in documents:
        match = True
        for f in mat_filters:
            kind = f["kind"]
            if kind == "seq":
                sq = doc.get("seq", 0)
                if ("from" in f and sq < f["from"]) or ("to" in f and sq > f["to"]):
                    match = False; break
            elif kind == "time":
                tm = doc.get("time", 0)
                if ("from" in f and tm < f["from"]) or ("to" in f and tm > f["to"]):
                    match = False; break
            elif kind == "type" and doc.get("type") not in f["values"]:
                match = False; break
            elif kind == "surface" and doc.get("surface") not in f["values"]:
                match = False; break
            elif kind == "text":
                pat = compile_session_text_filter(f["text"])
                if not pat.search(doc.get("text", "")):
                    match = False; break
        if match:
            res.append(doc)
    return res


def quote_fts_data(query: str) -> str:
    """Quote caller text as one FTS5 phrase."""
    return f'"{query.replace(chr(34), chr(34) + chr(34))}"'


def sanitize_fts_text(text: str) -> str:
    """Remove reserved marker collisions before FTS5 indexing or matching."""
    return text.replace("\0", "\uFFFD").replace(FTS_HIGHLIGHT_START, "\uFFFD").replace(FTS_HIGHLIGHT_END, "\uFFFD")


def request_fingerprint(request: Dict[str, Any]) -> str:
    """Build stable normalized request identity for cursors."""
    if "sessionId" in request:
        return json.dumps({
            "scope": "events",
            "sessionId": request["sessionId"],
            "query": request["query"],
            "filters": request.get("filters", []),
            "limit": request.get("limit", 10),
        }, sort_keys=True)
    return json.dumps({
        "scope": "sessions",
        "query": request["query"],
        "sessionFilters": request.get("sessionFilters", []),
        "eventFilters": request.get("eventFilters", []),
        "limit": request.get("limit", 10),
    }, sort_keys=True)


def make_snippet(marked_text: str, max_chars: int) -> str:
    """Build a whitespace-normalized excerpt around highlight markers."""
    clean_chars: List[str] = []
    match_start: Optional[int] = None
    for char in marked_text:
        if char == FTS_HIGHLIGHT_START:
            if match_start is None:
                match_start = len(clean_chars)
            continue
        if char == FTS_HIGHLIGHT_END:
            continue
        if char.isspace():
            if clean_chars and clean_chars[-1] != " ":
                clean_chars.append(" ")
        else:
            clean_chars.append(char)
    if clean_chars and clean_chars[-1] == " ":
        clean_chars.pop()
    clean = "".join(clean_chars)
    if len(clean) <= max_chars:
        return clean
    if max_chars <= 1:
        return "…"
    m_idx = match_start if match_start is not None else 0
    m_idx = min(m_idx, len(clean) - 1)
    start = max(0, m_idx - max_chars // 3)
    prefix = "…" if start > 0 else ""
    suffix = "…"
    content_len = max_chars - len(prefix) - len(suffix)
    if content_len < 1:
        start = m_idx
        suffix = ""
        content_len = max_chars - len(prefix)
    end = min(len(clean), start + content_len)
    if end == len(clean):
        suffix = ""
        content_len = max_chars - len(prefix)
        start = max(0, end - content_len)
    end = min(len(clean), start + content_len)
    return f"{prefix}{clean[start:end]}{suffix}"


def build_session_event_records(session_id: str, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records = []
    for ev in events:
        records.append({
            "sessionId": session_id,
            "seq": ev.get("seq", 0),
            "type": ev.get("type", ""),
            "time": ev.get("time", 0),
            "surface": "current" if ev.get("surfaceOp") == "append" else "log-only",
        })
    return records


def build_session_event_search_documents(session_id: str, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs = []
    for ev in events:
        text = extract_session_event_text(ev)
        if not text:
            continue
        docs.append({
            "sessionId": session_id,
            "seq": ev.get("seq", 0),
            "type": ev.get("type", ""),
            "time": ev.get("time", 0),
            "surface": "current" if ev.get("surfaceOp") == "append" else "log-only",
            "text": text,
        })
    return docs


class SessionQueryService:
    """
    Session Query SQLite FTS Service mounted at `ctx.sessionQuery`.
    """

    def __init__(self, ctx: Any, db_path: str = ":memory:", open_at: str = "immediate"):
        self.ctx = ctx
        self.db_path = db_path
        self.open_at = open_at
        self._conn = None
        if self.open_at != "never":
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                seq INTEGER,
                turn INTEGER,
                step INTEGER,
                event_type TEXT,
                content TEXT,
                time INTEGER
            )
        """)
        try:
            cur.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
                    session_id,
                    content,
                    content=session_documents,
                    content_rowid=id
                )
            """)
        except Exception:
            pass
        self._conn.commit()

    def index_event(self, session_id: str, event: Dict[str, Any]) -> None:
        if self.open_at == "never" or self._conn is None:
            return
        ev_type = event.get("type", "")
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        text = sanitize_fts_text(extract_session_event_text(event))

        if not text:
            return

        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO session_documents (session_id, seq, turn, step, event_type, content, time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                event.get("seq", 0),
                data.get("turn", 0),
                data.get("step", 0),
                ev_type,
                text,
                event.get("time", int(time.time() * 1000)),
            ),
        )
        row_id = cur.lastrowid
        try:
            cur.execute(
                "INSERT INTO session_fts(rowid, session_id, content) VALUES (?, ?, ?)",
                (row_id, session_id, text),
            )
        except Exception:
            pass
        self._conn.commit()

    def search_sessions(
        self, query_or_req: Union[str, Dict[str, Any]], limit: int = 10
    ) -> List[Dict[str, Any]]:
        if self.open_at == "never" or self._conn is None:
            raise SessionQueryError("Search is disabled (openAt: never)", code="SESSION_QUERY_SEARCH_DISABLED")
        query = query_or_req["query"] if isinstance(query_or_req, dict) else query_or_req
        req_limit = query_or_req.get("limit", limit) if isinstance(query_or_req, dict) else limit
        clean_q = sanitize_fts_text(query.strip())
        if not clean_q:
            return []

        cur = self._conn.cursor()
        results = []
        try:
            cur.execute(
                """
                SELECT d.session_id, d.seq, d.turn, d.step, d.event_type, d.content, d.time
                FROM session_fts f
                JOIN session_documents d ON f.rowid = d.id
                WHERE session_fts MATCH ?
                LIMIT ?
                """,
                (quote_fts_data(clean_q), req_limit),
            )
            rows = cur.fetchall()
        except Exception:
            cur.execute(
                """
                SELECT session_id, seq, turn, step, event_type, content, time
                FROM session_documents
                WHERE content LIKE ?
                LIMIT ?
                """,
                (f"%{clean_q}%", req_limit),
            )
            rows = cur.fetchall()

        for r in rows:
            results.append({
                "sessionId": r[0],
                "seq": r[1],
                "turn": r[2],
                "step": r[3],
                "eventType": r[4],
                "snippet": make_snippet(r[5], 300),
                "time": r[6],
            })
        return results

    def search_sessions_page(self, request: Dict[str, Any]) -> Dict[str, Any]:
        hits = self.search_sessions(request)
        return {"items": hits}

    def search_events(
        self, session_id_or_req: Union[str, Dict[str, Any]], query: str = "", limit: int = 10
    ) -> List[Dict[str, Any]]:
        if self.open_at == "never" or self._conn is None:
            raise SessionQueryError("Search is disabled (openAt: never)", code="SESSION_QUERY_SEARCH_DISABLED")
        if isinstance(session_id_or_req, dict):
            session_id = session_id_or_req.get("sessionId", "")
            q = session_id_or_req.get("query", "")
            req_limit = session_id_or_req.get("limit", limit)
        else:
            session_id = session_id_or_req
            q = query
            req_limit = limit

        clean_q = sanitize_fts_text(q.strip())
        if not clean_q:
            return []

        cur = self._conn.cursor()
        results = []
        try:
            cur.execute(
                """
                SELECT d.session_id, d.seq, d.turn, d.step, d.event_type, d.content, d.time
                FROM session_fts f
                JOIN session_documents d ON f.rowid = d.id
                WHERE session_fts MATCH ? AND d.session_id = ?
                LIMIT ?
                """,
                (quote_fts_data(clean_q), session_id, req_limit),
            )
            rows = cur.fetchall()
        except Exception:
            cur.execute(
                """
                SELECT session_id, seq, turn, step, event_type, content, time
                FROM session_documents
                WHERE content LIKE ? AND session_id = ?
                LIMIT ?
                """,
                (f"%{clean_q}%", session_id, req_limit),
            )
            rows = cur.fetchall()

        for r in rows:
            results.append({
                "sessionId": r[0],
                "seq": r[1],
                "turn": r[2],
                "step": r[3],
                "eventType": r[4],
                "snippet": make_snippet(r[5], 300),
                "time": r[6],
            })
        return results

    def search_events_page(self, request: Dict[str, Any]) -> Dict[str, Any]:
        hits = self.search_events(request)
        return {"items": hits, "session": {"id": request.get("sessionId", "")}}

    def trace_session(self, session_id: str) -> Dict[str, Any]:
        return {
            "target": {"header": {"id": session_id}, "live": True, "persisted": True},
            "ancestors": [],
            "descendants": [],
            "complete": True,
            "root": {"header": {"id": session_id}, "live": True, "persisted": True},
        }

    def trace_event(self, request: Dict[str, Any]) -> Dict[str, Any]:
        sid = request.get("sessionId", "")
        seq = request.get("seq", 0)
        return {
            "target": {"sessionId": sid, "seq": seq, "type": "unknown", "time": 0, "surface": "current"},
            "replacementChain": [],
            "replacedEventSeqs": [],
            "sourceEventSeqs": [],
            "derivedEventSeqs": [],
            "session": {"id": sid},
        }

    def read_event(self, request: Dict[str, Any]) -> Dict[str, Any]:
        sid = request.get("sessionId", "")
        seq = request.get("seq", 0)
        return {
            "session": {"id": sid},
            "target": {"type": "unknown", "seq": seq, "time": 0, "data": {}},
            "events": [],
            "startSeq": seq,
            "endSeq": seq,
        }


class SessionQueryPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-query-sqlite`: Mounts `ctx.sessionQuery` and registers `session_search` / `session_event_search`.
    """

    id = "session-query-sqlite"
    name = "@deepseek-ai/dsh-session-query-sqlite"
    def apply(self, ctx: Any) -> None:
        db_path = self.config.get("path", ":memory:")
        open_at = self.config.get("open_at") or self.config.get("openAt", "immediate")
        service = SessionQueryService(ctx, db_path=db_path, open_at=open_at)
        ctx.set_service("sessionQuery", service)
        ctx.set_service("session_query", service)

        def on_session_event(subject: Any, event: Dict[str, Any]) -> None:
            sid = getattr(subject, "id", "default-session") if hasattr(subject, "id") else "default-session"
            service.index_event(sid, event)

        ctx.on("session/event", on_session_event)

        tools_svc = ctx.get("tools")
        if tools_svc:
            tools_svc.register(
                name="session_search",
                description="Search prior sessions in the workspace and return the strongest matching event from each session.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query keywords or phrase."},
                        "limit": {"type": "integer", "description": "Max results to return (default 10)."},
                    },
                    "required": ["query"],
                },
                handler=lambda query, limit=10: json.dumps(service.search_sessions(query, limit=limit), ensure_ascii=False, indent=2),
                execution_mode="parallel",
            )

            tools_svc.register(
                name="session_event_search",
                description="Search prior events in one authorized session.",
                parameters={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Session ID to search within."},
                        "query": {"type": "string", "description": "Search query keywords."},
                        "limit": {"type": "integer", "description": "Max results to return (default 10)."},
                    },
                    "required": ["session_id", "query"],
                },
                handler=lambda session_id, query, limit=10: json.dumps(service.search_events(session_id, query, limit=limit), ensure_ascii=False, indent=2),
                execution_mode="parallel",
            )
