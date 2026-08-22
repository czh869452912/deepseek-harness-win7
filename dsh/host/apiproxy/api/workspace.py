"""
Workspace Domain Handler (`@deepseek-ai/dsh-apiproxy/api/workspace`).
Handles all 8 workspace RPC methods aligned 1:1 with reference `api/workspace.ts`.
"""

import os
import time
from typing import Any, Dict, List, Set
from dsh.core.session import SessionStore


def hashlib_short(data: bytes) -> str:
    import hashlib
    return hashlib.sha1(data).hexdigest()[:8]


class WorkspaceDomainHandler:
    def __init__(
        self,
        ctx: Any,
        workspaces: Dict[str, Any],
        workspace_order: List[str],
        archived_sessions: Set[str],
        active_sessions: Dict[str, Any],
        broadcast_host: Any,
    ):
        self.ctx = ctx
        self._workspaces = workspaces
        self._workspace_order = workspace_order
        self._archived_sessions = archived_sessions
        self._active_sessions = active_sessions
        self._broadcast_host = broadcast_host

    async def list_workspaces(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "items": list(self._workspaces.values()),
            "archivedSessionIds": list(self._archived_sessions),
        }

    async def create_workspace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw_path = payload.get("path", os.getcwd())
        ws_path = os.path.normpath(raw_path).replace("\\", "/")
        ws_id = f"ws-{hashlib_short(ws_path.encode('utf-8'))}"
        created = (ws_id not in self._workspaces)

        if created:
            sessions_svc: SessionStore = self.ctx.get("sessions")
            agent_loop = self.ctx.get("agent_loop")
            sid = f"session-{os.urandom(4).hex()}"

            if sessions_svc:
                s = sessions_svc.create(sid)
                s.header.cwd = ws_path
                s.header.agent_preset = "standard"
            if agent_loop:
                handle = await agent_loop.create_agent(session_id=sid)
                self._active_sessions[sid] = handle

            ws_view = {
                "workspaceId": ws_id,
                "path": ws_path,
                "title": os.path.basename(ws_path) or "root",
                "sessionIds": [sid],
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self._workspaces[ws_id] = ws_view
            self._workspace_order.append(ws_id)

            await self._broadcast_host({
                "type": "host/session-added",
                "sessionId": sid,
                "blank": True,
                "cwd": ws_path,
                "agentPreset": "standard",
            })
            await self._broadcast_host({
                "type": "host/workspace-changed",
                "workspace": ws_view,
            })
            await self._broadcast_host({
                "type": "host/workspace-order-changed",
                "workspaceIds": list(self._workspace_order),
            })
        else:
            ws_view = self._workspaces[ws_id]

        return {"workspace": ws_view, "created": created}

    async def rename_workspace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ws_id = payload.get("workspaceId")
        new_title = payload.get("title", "").strip()
        if ws_id in self._workspaces:
            self._workspaces[ws_id]["title"] = new_title
            self._workspaces[ws_id]["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            await self._broadcast_host({"type": "host/workspace-changed", "workspace": self._workspaces[ws_id]})
            return {"workspace": self._workspaces[ws_id]}
        raise ValueError(f"Workspace {ws_id} not found")

    async def delete_workspace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ws_id = payload.get("workspaceId")
        if ws_id in self._workspaces:
            del self._workspaces[ws_id]
            if ws_id in self._workspace_order:
                self._workspace_order.remove(ws_id)
            await self._broadcast_host({"type": "host/workspace-removed", "workspaceId": ws_id})
            await self._broadcast_host({"type": "host/workspace-order-changed", "workspaceIds": list(self._workspace_order)})
            return {"deleted": True}
        raise ValueError(f"Workspace {ws_id} not found")

    async def insert_before(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ws_id = payload.get("workspaceId")
        before_id = payload.get("beforeWorkspaceId")
        if ws_id in self._workspace_order:
            self._workspace_order.remove(ws_id)
            if before_id and before_id in self._workspace_order:
                idx = self._workspace_order.index(before_id)
                self._workspace_order.insert(idx, ws_id)
            else:
                self._workspace_order.append(ws_id)
            await self._broadcast_host({"type": "host/workspace-order-changed", "workspaceIds": list(self._workspace_order)})
        return {"workspaceIds": list(self._workspace_order)}

    async def insert_session_before(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ws_id = payload.get("workspaceId")
        sid = payload.get("sessionId")
        before_sid = payload.get("beforeSessionId")
        if ws_id in self._workspaces:
            s_list = self._workspaces[ws_id]["sessionIds"]
            if sid in s_list:
                s_list.remove(sid)
            if before_sid and before_sid in s_list:
                idx = s_list.index(before_sid)
                s_list.insert(idx, sid)
            else:
                s_list.append(sid)
            self._workspaces[ws_id]["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            await self._broadcast_host({"type": "host/workspace-changed", "workspace": self._workspaces[ws_id]})
            return {"workspace": self._workspaces[ws_id]}
        raise ValueError(f"Workspace {ws_id} not found")

    async def archive_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId")
        if sid:
            self._archived_sessions.add(sid)
            await self._broadcast_host({
                "type": "host/archived-sessions-changed",
                "archivedSessionIds": list(self._archived_sessions),
            })
        return {"archivedSessionIds": list(self._archived_sessions)}

    async def list_files(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cwd = os.getcwd()
        ignore = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", ".gemini"}
        files = []
        for root, dirs, filenames in os.walk(cwd):
            dirs[:] = [d for d in dirs if d not in ignore and not d.startswith(".")]
            rel_dir = os.path.relpath(root, cwd)
            for f in filenames:
                if f.startswith(".") or f.endswith(".pyc"):
                    continue
                p = os.path.normpath(f if rel_dir == "." else os.path.join(rel_dir, f)).replace("\\", "/")
                files.append({"path": p, "name": f, "ext": os.path.splitext(f)[1].lstrip(".")})
                if len(files) >= 400:
                    break
            if len(files) >= 400:
                break
        return {"files": files, "cwd": cwd}
