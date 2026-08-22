"""
Session Search Domain Handler (`@deepseek-ai/dsh-apiproxy/api/session-search`).
Handles `session.search`. Aligned 1:1 with reference `api/session-search.ts`.
"""

import json
from typing import Any, Dict
from dsh.core.session import SessionStore


class SessionSearchDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def search_sessions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        query_str = payload.get("query", "")
        sid = payload.get("sessionId")
        sessions_svc: SessionStore = self.ctx.get("sessions")
        matches = []
        if sessions_svc:
            target_sessions = [sessions_svc._sessions[sid]] if sid and sid in sessions_svc._sessions else sessions_svc._sessions.values()
            for s in target_sessions:
                for ev in s.events:
                    if query_str and query_str.lower() in json.dumps(ev, ensure_ascii=False).lower():
                        matches.append({"sessionId": s.session_id, "event": ev})
        return {"matches": matches, "query": query_str}
