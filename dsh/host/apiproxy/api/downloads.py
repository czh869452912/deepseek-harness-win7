"""
Downloads Domain Handler (`@deepseek-ai/dsh-apiproxy/api/downloads`).
Handles session export downloads (/api/session.export).
Aligned 1:1 with reference `api/downloads.ts`.
"""

from typing import Any, Dict
from dsh.host.apiproxy.session_export import export_session_ndjson, export_session_zip


class DownloadsDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    def export_session(self, session_id: str, format_kind: str) -> Dict[str, Any]:
        sessions_svc = self.ctx.get("sessions")
        events = []
        if sessions_svc and session_id in sessions_svc._sessions:
            events = sessions_svc._sessions[session_id].events

        if format_kind in ("ndjson", "jsonl"):
            content = export_session_ndjson(session_id, events)
            return {
                "content_type": "application/x-ndjson; charset=utf-8",
                "filename": f"session-{session_id}.jsonl",
                "body": content,
            }

        zip_bytes = export_session_zip(session_id, events)
        return {
            "content_type": "application/zip",
            "filename": f"session-{session_id}.zip",
            "body": zip_bytes,
        }
