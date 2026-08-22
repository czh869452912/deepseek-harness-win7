"""
Workspace entity registry (`ctx.workspaces`): durable workspace roots and session bindings.
Aligned 1:1 with official `@deepseek-ai/dsh-workspace`.
"""

import hashlib
import os
import time
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


def hashlib_short(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:8]


class WorkspaceEntity:
    def __init__(
        self,
        workspace_id: str,
        path: str,
        title: str,
        session_ids: Optional[List[str]] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ):
        self.workspace_id = workspace_id
        self.path = os.path.normpath(path).replace("\\", "/")
        self.title = title
        self.session_ids = session_ids or []
        self.created_at = created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.updated_at = updated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspaceId": self.workspace_id,
            "path": self.path,
            "title": self.title,
            "sessionIds": self.session_ids,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class WorkspaceService:
    """Workspace Entity Registry mounted at `ctx.workspaces`."""

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._workspaces: Dict[str, WorkspaceEntity] = {}
        self._order: List[str] = []

    def get(self, ws_id: str) -> Optional[WorkspaceEntity]:
        return self._workspaces.get(ws_id)

    def get_by_path(self, path: str) -> Optional[WorkspaceEntity]:
        norm = os.path.normpath(path).replace("\\", "/")
        for ws in self._workspaces.values():
            if ws.path == norm:
                return ws
        return None

    def list_workspaces(self) -> List[WorkspaceEntity]:
        return [self._workspaces[wid] for wid in self._order if wid in self._workspaces]

    def create(self, path: str, title: Optional[str] = None) -> WorkspaceEntity:
        norm = os.path.normpath(path).replace("\\", "/")
        ws_id = f"ws-{hashlib_short(norm.encode('utf-8'))}"
        if ws_id in self._workspaces:
            ws = self._workspaces[ws_id]
            if title:
                ws.title = title
            ws.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return ws

        ws_title = title or os.path.basename(norm) or "workspace"
        ws = WorkspaceEntity(
            workspace_id=ws_id,
            path=norm,
            title=ws_title,
        )
        self._workspaces[ws_id] = ws
        if ws_id not in self._order:
            self._order.append(ws_id)

        if self.ctx and hasattr(self.ctx, "emit"):
            try:
                self.ctx.emit("workspace:created", ws.to_dict())
            except Exception:
                pass
        return ws

    def bind_session(self, ws_id: str, session_id: str) -> None:
        ws = self.get(ws_id)
        if ws and session_id not in ws.session_ids:
            ws.session_ids.append(session_id)
            ws.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if self.ctx and hasattr(self.ctx, "emit"):
                try:
                    self.ctx.emit("workspace:session-bound", {"workspaceId": ws_id, "sessionId": session_id})
                except Exception:
                    pass

    def unbind_session(self, ws_id: str, session_id: str) -> None:
        ws = self.get(ws_id)
        if ws and session_id in ws.session_ids:
            ws.session_ids.remove(session_id)
            ws.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if self.ctx and hasattr(self.ctx, "emit"):
                try:
                    self.ctx.emit("workspace:session-unbound", {"workspaceId": ws_id, "sessionId": session_id})
                except Exception:
                    pass

    def touch(self, ws_id: str) -> None:
        ws = self.get(ws_id)
        if ws:
            ws.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def delete(self, ws_id: str) -> None:
        if ws_id in self._workspaces:
            ws = self._workspaces.pop(ws_id)
            if ws_id in self._order:
                self._order.remove(ws_id)
            if self.ctx and hasattr(self.ctx, "emit"):
                try:
                    self.ctx.emit("workspace:deleted", {"workspaceId": ws_id})
                except Exception:
                    pass


class WorkspacePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-workspace`: Mounts `ctx.workspaces` service.
    """

    id = "workspace"
    name = "@deepseek-ai/dsh-workspace"

    def apply(self, ctx: Any) -> None:
        svc = WorkspaceService(ctx)
        ctx.set_service("workspaces", svc)
        ctx.set_service("workspaceRegistry", svc)
