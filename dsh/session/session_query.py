"""
Session query service with SQLite FTS5 index, semantic document extraction, and model-facing search tools.
Aligned 1:1 with official `@deepseek-ai/dsh-session-query-sqlite` and `@deepseek-ai/dsh-tool-session-query`.
"""

import json
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.plugin import Plugin


def extract_session_event_text(event: Dict[str, Any]) -> str:
    """
    Extract searchable semantic text from one session event.
    """
    etype = event.get("type", "")
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}

    if etype == "user/message":
        content = data.get("content")
        if content is None and "message" in data and isinstance(data["message"], dict):
            content = data["message"].get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        return json.dumps(content, ensure_ascii=False) if content else ""
    elif etype == "assistant/message":
        msg = data.get("message", {})
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") in ("text", "reasoning"))
        return ""
    elif etype == "tool/call":
        name = data.get("name", "")
        args = data.get("arguments", "")
        return f"{name} {args}" if isinstance(args, str) else f"{name} {json.dumps(args, ensure_ascii=False)}"
    elif etype == "tool/result":
        res = data.get("result", "")
        msg = data.get("message", {})
        if not res and isinstance(msg, dict):
            content = msg.get("content", [])
            if isinstance(content, list):
                res = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        err = data.get("error", {})
        err_str = f"{err.get('name', '')} {err.get('code', '')}" if isinstance(err, dict) else ""
        return f"{res} {err_str}".strip()
    elif etype == "todo/write":
        todos = data.get("todos", [])
        if isinstance(todos, list):
            return " ".join(f"{t.get('status', '')} {t.get('content', '')}" for t in todos if isinstance(t, dict))
    elif etype == "session/title":
        return data.get("title", "")

    return ""


def filter_session_results(
    records: List[Dict[str, Any]],
    filters: Optional[List[Callable[[Dict[str, Any]], bool]]] = None,
) -> List[Dict[str, Any]]:
    """
    Apply ANDed logical-session filters while preserving input order.
    """
    if not filters:
        return list(records)
    res = []
    for rec in records:
        if all(f(rec) for f in filters):
            res.append(rec)
    return res


def event_records(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Classify a raw event log with lightweight records.
    """
    records = []
    for ev in events:
        records.append({
            "seq": ev.get("seq", 0),
            "type": ev.get("type", ""),
            "time": ev.get("time", 0),
            "surface": "current" if ev.get("surfaceOp") == "append" else "log-only",
        })
    return records


class SessionQueryService:
    """
    Session Query SQLite FTS Service mounted at `ctx.sessionQuery`.
    """

    def __init__(self, ctx: Any, db_path: str = ":memory:"):
        self.ctx = ctx
        self.db_path = db_path
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
        ev_type = event.get("type", "")
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        text = extract_session_event_text(event)

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

    def search_sessions(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
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
                (query, limit),
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
                (f"%{query}%", limit),
            )
            rows = cur.fetchall()

        for r in rows:
            results.append({
                "sessionId": r[0],
                "seq": r[1],
                "turn": r[2],
                "step": r[3],
                "eventType": r[4],
                "snippet": r[5][:300] + "..." if len(r[5]) > 300 else r[5],
                "time": r[6],
            })
        return results

    def search_events(self, session_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
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
                (query, session_id, limit),
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
                (f"%{query}%", session_id, limit),
            )
            rows = cur.fetchall()

        for r in rows:
            results.append({
                "sessionId": r[0],
                "seq": r[1],
                "turn": r[2],
                "step": r[3],
                "eventType": r[4],
                "snippet": r[5][:300] + "..." if len(r[5]) > 300 else r[5],
                "time": r[6],
            })
        return results


class SessionQueryPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-query-sqlite`: Mounts `ctx.sessionQuery` and registers `session_search` / `session_event_search`.
    """

    id = "session-query-sqlite"
    name = "@deepseek-ai/dsh-session-query-sqlite"

    def apply(self, ctx: Any) -> None:
        db_path = self.config.get("path", ":memory:")
        service = SessionQueryService(ctx, db_path=db_path)
        ctx.set_service("sessionQuery", service)

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
