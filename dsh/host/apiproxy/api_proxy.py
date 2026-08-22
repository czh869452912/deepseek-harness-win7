"""
API Proxy Bridge Plugin (`@deepseek-ai/dsh-apiproxy`).
Provides `/api/...` HTTP RPC endpoints and dual SSE event streams (mux + host) for the Web GUI.
Aligned 1:1 with official DeepSeek Harness ApiProxy & Fetch carrier protocol.
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import urllib.parse

from dsh.cordis.plugin import Plugin
from dsh.core.session import Session, SessionStore
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService


def hashlib_short(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:8]


def format_sse_frame(payload: Dict[str, Any], rpc_id: Optional[str] = None) -> bytes:
    """Format SSE data line according to official ServerRequest schema."""
    frame_rpc_id = rpc_id or str(uuid.uuid4())
    frame_type = payload.get("type", "unknown")
    envelope = {
        "type": "server-request",
        "rpcId": frame_rpc_id,
        "method": frame_type,
        "payload": payload,
    }
    return f"data: {json.dumps(envelope, ensure_ascii=False, default=str)}\n\n".encode("utf-8")


class ApiProxyPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-apiproxy`: Connects Web GUI to Cordis context, agents, and sessions.
    """

    id = "apiproxy"
    name = "@deepseek-ai/dsh-apiproxy"
    inject = ["web_server"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._mux_clients: List[asyncio.Queue] = []
        self._host_clients: List[asyncio.Queue] = []
        self._active_sessions: Dict[str, Any] = {}
        self._pending_server_requests: Dict[str, asyncio.Future] = {}
        self._workspaces: Dict[str, Dict[str, Any]] = {}
        self._archived_sessions: Set[str] = set()
        self._workspace_order: List[str] = []
        self._background_jobs: Dict[str, List[Dict[str, Any]]] = {}

    def apply(self, ctx: Any) -> None:
        web_server: WebServerService = ctx.get("web_server") or ctx.get("webServer")
        if not web_server:
            return

        sessions_svc: SessionStore = ctx.get("sessions")
        cwd = os.path.normpath(os.getcwd()).replace("\\", "/")
        ws_id = f"ws-{hashlib_short(cwd.encode('utf-8'))}"

        # Ensure default session is created and bound to default workspace
        if sessions_svc:
            if "default-session" not in sessions_svc._sessions:
                s = sessions_svc.create("default-session")
                s.header.cwd = cwd
                s.header.agent_preset = "standard"
            else:
                sessions_svc._sessions["default-session"].header.cwd = cwd

        self._workspaces[ws_id] = {
            "workspaceId": ws_id,
            "path": cwd,
            "title": os.path.basename(cwd) or "root",
            "sessionIds": ["default-session"],
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._workspace_order = [ws_id]

        # Register /api prefix routes
        disposer = web_server.register("prefix", "/api", self._handle_api_request)
        if hasattr(ctx, "effect"):
            ctx.effect(lambda: disposer)

        # Hook session & agent events to broadcast via dual streams
        ctx.on("session/event", self._on_session_event)
        ctx.on("session/append", self._on_session_event)
        ctx.on("session/chunk", self._on_session_chunk)
        ctx.on("assistant/chunk", self._on_assistant_chunk)
        ctx.on("agent/status", self._on_agent_status)
        ctx.on("goal/changed", self._on_goal_changed)
        ctx.on("goal/change", self._on_goal_changed)
        ctx.on("question/requested", self._on_question_requested)
        ctx.on("approval/requested", self._on_approval_requested)
        ctx.on("projection/change", self._on_projection_change)


    async def _broadcast_mux(self, frame: Dict[str, Any], rpc_id: Optional[str] = None) -> None:
        try:
            payload = format_sse_frame(frame, rpc_id=rpc_id)
            for q in list(self._mux_clients):
                try:
                    await q.put(payload)
                except Exception:
                    pass
        except Exception:
            pass

    async def _broadcast_host(self, frame: Dict[str, Any], rpc_id: Optional[str] = None) -> None:
        try:
            payload = format_sse_frame(frame, rpc_id=rpc_id)
            for q in list(self._host_clients):
                try:
                    await q.put(payload)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_session_chunk(self, *args: Any, **kwargs: Any) -> None:
        try:
            chunk = args[1] if len(args) >= 2 else (args[0] if args else {})
            sid = args[0] if len(args) >= 2 and isinstance(args[0], str) else "default-session"
            if isinstance(chunk, dict):
                asyncio.create_task(self._broadcast_mux({
                    "type": "session/event",
                    "sessionId": sid,
                    "event": {"type": "session/chunk", "data": chunk},
                }))
        except Exception:
            pass

    def _on_assistant_chunk(self, *args: Any, **kwargs: Any) -> None:
        try:
            chunk = args[0] if args else {}
            if isinstance(chunk, dict):
                asyncio.create_task(self._broadcast_mux({
                    "type": "session/event",
                    "sessionId": "default-session",
                    "event": {"type": "assistant/chunk", "data": chunk},
                }))
        except Exception:
            pass

    def _on_session_event(self, *args: Any, **kwargs: Any) -> None:
        try:
            event = args[1] if len(args) >= 2 else (args[0] if args else None)
            sid = args[0] if len(args) >= 2 and isinstance(args[0], str) else "default-session"
            if isinstance(event, dict):
                asyncio.create_task(self._broadcast_mux({
                    "type": "session/event",
                    "sessionId": sid,
                    "event": event,
                }))
        except Exception:
            pass

    def _on_agent_status(self, *args: Any, **kwargs: Any) -> None:
        try:
            payload = args[0] if args else {}
            status_str = "idle"
            sid = "default-session"
            if isinstance(payload, dict):
                status_str = str(payload.get("status", "idle"))
                agent = payload.get("agent")
                if agent and hasattr(agent, "session_id"):
                    sid = getattr(agent, "session_id", sid)
            else:
                status_str = str(payload)

            asyncio.create_task(self._broadcast_host({
                "type": "host/session-status",
                "sessionId": sid,
                "running": (status_str == "running"),
            }))
        except Exception:
            pass

    def _on_goal_changed(self, *args: Any, **kwargs: Any) -> None:
        try:
            goal = args[0] if args else None
            goal_data = goal.to_dict() if (goal and hasattr(goal, "to_dict")) else goal
            sid = args[1] if len(args) >= 2 and isinstance(args[1], str) else "default-session"
            asyncio.create_task(self._broadcast_mux({
                "type": "session/projection",
                "sessionId": sid,
                "key": "goal",
                "value": goal_data,
                "seq": int(time.time()),
            }))
        except Exception:
            pass

    def _on_projection_change(self, *args: Any, **kwargs: Any) -> None:
        try:
            payload = args[0] if args else {}
            if isinstance(payload, dict):
                sid = payload.get("sessionId") or "default-session"
                asyncio.create_task(self._broadcast_mux({
                    "type": "session/projection",
                    "sessionId": sid,
                    "key": payload.get("key"),
                    "value": payload.get("value"),
                    "seq": payload.get("seq", int(time.time())),
                }))
        except Exception:
            pass


    def _on_question_requested(self, *args: Any, **kwargs: Any) -> None:
        try:
            q = args[0] if args else {}
            rpc_id = q.get("rpcId") or f"q-{time.time()}"
            sid = q.get("sessionId", "default-session")
            loop = asyncio.get_event_loop()
            fut = loop.create_future()
            self._pending_server_requests[rpc_id] = fut

            questions_list = q.get("questions") if isinstance(q.get("questions"), list) else [q]
            asyncio.create_task(self._broadcast_mux({
                "type": "question/requested",
                "sessionId": sid,
                "questions": questions_list,
            }, rpc_id=rpc_id))
        except Exception:
            pass

    def _on_approval_requested(self, *args: Any, **kwargs: Any) -> None:
        try:
            appr = args[0] if args else {}
            rpc_id = appr.get("approvalId") or appr.get("rpcId") or f"appr-{time.time()}"
            sid = appr.get("sessionId", "default-session")
            loop = asyncio.get_event_loop()
            fut = loop.create_future()
            self._pending_server_requests[rpc_id] = fut

            asyncio.create_task(self._broadcast_mux({
                "type": "approval/requested",
                "sessionId": sid,
                "approvalId": rpc_id,
                "toolName": appr.get("toolName", "tool"),
                "reason": appr.get("reason", ""),
            }, rpc_id=rpc_id))
        except Exception:
            pass

    async def _handle_api_request(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        path = request.get("path", "")
        method = request.get("method", "GET")

        # CORS headers
        response.write_header("Access-Control-Allow-Origin", "*")
        response.write_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        response.write_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

        if method == "OPTIONS":
            response.write_status(204)
            await response.finish()
            return

        # Dual Streaming SSE Endpoints (/api/events.mux, /api/events/mux, /api/events.host, /api/events/host)
        if path in ("/api/events.mux", "/api/events/mux", "/api/session/events"):
            await self._handle_mux_stream(request, response)
            return
        if path in ("/api/events.host", "/api/events/host"):
            await self._handle_host_stream(request, response)
            return

        async def send_json(data: Any, status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            response.write_status(status)
            response.write_header("Content-Type", "application/json; charset=utf-8")
            response.write_body(body)
            await response.finish()

        parsed_query = urllib.parse.parse_qs(request.get("query", ""))
        body_json: Dict[str, Any] = {}
        if request.get("body"):
            try:
                body_json = json.loads(request["body"].decode("utf-8"))
            except Exception:
                pass

        # Check for official client-request RPC envelope
        is_rpc_envelope = isinstance(body_json, dict) and body_json.get("type") == "client-request"
        rpc_id = body_json.get("rpcId") if is_rpc_envelope else None
        req_payload: Dict[str, Any] = body_json.get("payload", {}) if is_rpc_envelope else body_json

        async def send_rpc_success(value: Any) -> None:
            if is_rpc_envelope:
                await send_json({
                    "type": "server-response",
                    "rpcId": rpc_id,
                    "result": {
                        "ok": True,
                        "value": value,
                    }
                })
            else:
                await send_json({
                    **(value if isinstance(value, dict) else {"value": value}),
                    "result": {"ok": True, "value": value},
                })

        async def send_rpc_error(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
            if is_rpc_envelope:
                await send_json({
                    "type": "server-response",
                    "rpcId": rpc_id,
                    "result": {
                        "ok": False,
                        "error": {
                            "code": code,
                            "message": message,
                            "details": details or {},
                        }
                    }
                })
            else:
                await send_json({
                    "error": message,
                    "code": code,
                    "result": {
                        "ok": False,
                        "error": {
                            "code": code,
                            "message": message,
                            "details": details or {},
                        }
                    }
                }, 400)

        # Server-Request Answer Response (/api/respond)
        if path == "/api/respond" and method == "POST":
            resp_rpc_id = body_json.get("rpcId")
            sid = body_json.get("sessionId", "default-session")
            answer = body_json.get("answer")
            outcome = body_json.get("outcome")

            if resp_rpc_id and resp_rpc_id in self._pending_server_requests:
                fut = self._pending_server_requests.pop(resp_rpc_id)
                if not fut.done():
                    fut.set_result(answer or outcome or True)

            if answer is not None:
                await self._broadcast_mux({
                    "type": "question/resolved",
                    "sessionId": sid,
                    "questionRpcId": resp_rpc_id,
                    "outcome": "answered",
                })
            elif outcome is not None:
                await self._broadcast_mux({
                    "type": "approval/resolved",
                    "sessionId": sid,
                    "approvalId": body_json.get("approvalId", resp_rpc_id),
                    "outcome": outcome,
                })

            await send_json({"ok": True, "accepted": True, "success": True})
            return

        # Session export download (/api/session.export)
        if path in ("/api/session.export", "/api/session/export"):
            sid = parsed_query.get("sessionId", [None])[0] or req_payload.get("sessionId", "default-session")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            events = []
            if sessions_svc and sid in sessions_svc._sessions:
                events = sessions_svc._sessions[sid].events
            lines = [json.dumps(ev, ensure_ascii=False, default=str) for ev in events]
            export_content = "\n".join(lines).encode("utf-8")
            response.write_status(200)
            response.write_header("Content-Type", "application/x-ndjson; charset=utf-8")
            response.write_header("Content-Disposition", f'attachment; filename="session-{sid}.jsonl"')
            response.write_body(export_content)
            await response.finish()
            return

        # Extract method name from path
        rpc_method = path[5:] if path.startswith("/api/") else path

        # ── 1. Host Domain & Status ──
        if rpc_method in ("host.describe", "host/describe", "status"):
            llm = self.ctx.get("llm")
            plan_mode = self.ctx.get("plan_mode")
            goals = self.ctx.get("goals")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            effective_model = llm.resolve_model() if llm else "deepseek-chat"
            effective_base_url = llm.resolve_base_url() if llm else "https://api.deepseek.com/v1"
            effective_provider = "deepseek"
            cwd_path = os.getcwd().replace("\\", "/")
            home_path = os.path.expanduser("~").replace("\\", "/")
            plan_active = plan_mode.is_active() if plan_mode else False
            curr_goal = goals.get_goal() if goals else None

            await send_rpc_success({
                "status": "ready",
                "version": "0.1.0",
                "cwd": cwd_path,
                "provider": effective_provider,
                "model": effective_model,
                "baseUrl": effective_base_url,
                "planMode": plan_active,
                "goal": curr_goal.to_dict() if curr_goal else None,
                "attachedSessions": len(self._active_sessions),
                "sessionsCount": len(sessions_svc._sessions) if sessions_svc else 0,
                "home": home_path,
                "canOpenPath": True,
            })
            return

        if rpc_method in ("host.pickDirectory", "host/pickDirectory"):
            dp = self.ctx.get("directory_picker") or self.ctx.get("directoryPicker")
            selected_path = None
            if dp:
                cap = dp.capability()
                if cap.get("kind") == "native":
                    pick_fn = cap.get("pick")
                    if asyncio.iscoroutinefunction(pick_fn):
                        selected_path = await pick_fn()
                    elif callable(pick_fn):
                        selected_path = pick_fn()
                elif cap.get("kind") == "browse":
                    selected_path = None

            if selected_path:
                selected_path = os.path.normpath(selected_path).replace("\\", "/")
            await send_rpc_success({"path": selected_path})
            return

        if rpc_method in ("host.listDirectory", "host/listDirectory"):
            dp = self.ctx.get("directory_picker") or self.ctx.get("directoryPicker")
            target_path = req_payload.get("path") or parsed_query.get("path", [None])[0]
            if dp and dp.capability().get("kind") == "browse":
                res = await dp.capability()["list"](target_path)
                await send_rpc_success(res)
                return

            p = os.path.abspath(target_path or os.path.expanduser("~"))
            home = os.path.abspath(os.path.expanduser("~"))
            crumbs = []
            curr = p
            while True:
                name = os.path.basename(curr) or curr
                crumbs.insert(0, {"name": name, "path": curr.replace("\\", "/"), "hidden": False})
                parent = os.path.dirname(curr)
                if parent == curr:
                    break
                curr = parent

            entries = []
            try:
                for it in sorted(os.listdir(p)):
                    full = os.path.join(p, it)
                    if os.path.isdir(full):
                        entries.append({
                            "name": it,
                            "path": full.replace("\\", "/"),
                            "hidden": it.startswith("."),
                        })
            except Exception:
                pass

            await send_rpc_success({
                "path": p.replace("\\", "/"),
                "home": home.replace("\\", "/"),
                "crumbs": crumbs,
                "entries": entries,
                "truncated": False,
            })
            return

        if rpc_method in ("host.createDirectory", "host/createDirectory"):
            dp = self.ctx.get("directory_picker") or self.ctx.get("directoryPicker")
            p = req_payload.get("path", os.getcwd())
            n = req_payload.get("name", "New Folder")
            if dp and dp.capability().get("kind") == "browse":
                try:
                    res_path = await dp.capability()["createDirectory"](p, n)
                    await send_rpc_success({"path": res_path.replace("\\", "/")})
                    return
                except Exception as e:
                    await send_rpc_error("directory-create-failed", str(e))
                    return

            target = os.path.join(p, n)
            try:
                os.makedirs(target, exist_ok=False)
                await send_rpc_success({"path": os.path.abspath(target).replace("\\", "/")})
            except Exception as e:
                await send_rpc_error("directory-create-failed", str(e))
            return

        if rpc_method in ("host.openPath", "host/openPath"):
            target_path = req_payload.get("path")
            if target_path and os.path.exists(target_path):
                try:
                    if sys.platform == "win32":
                        os.startfile(target_path)
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", target_path])
                    else:
                        subprocess.Popen(["xdg-open", target_path])
                except Exception:
                    pass
            await send_rpc_success({"opened": True})
            return

        # ── 2. Workspace Domain ──
        if rpc_method in ("workspace.list", "workspace/list"):
            await send_rpc_success({
                "items": list(self._workspaces.values()),
                "archivedSessionIds": list(self._archived_sessions),
            })
            return

        if rpc_method in ("workspace.create", "workspace/create"):
            raw_path = req_payload.get("path", os.getcwd())
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

                # Broadcast session-added and workspace changes
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

            await send_rpc_success({"workspace": ws_view, "created": created})
            return

        if rpc_method in ("workspace.rename", "workspace/rename"):
            ws_id = req_payload.get("workspaceId")
            new_title = req_payload.get("title", "").strip()
            if ws_id in self._workspaces:
                self._workspaces[ws_id]["title"] = new_title
                self._workspaces[ws_id]["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                await self._broadcast_host({"type": "host/workspace-changed", "workspace": self._workspaces[ws_id]})
                await send_rpc_success({"workspace": self._workspaces[ws_id]})
            else:
                await send_rpc_error("workspace-not-found", f"Workspace {ws_id} not found")
            return

        if rpc_method in ("workspace.delete", "workspace/delete"):
            ws_id = req_payload.get("workspaceId")
            if ws_id in self._workspaces:
                del self._workspaces[ws_id]
                if ws_id in self._workspace_order:
                    self._workspace_order.remove(ws_id)
                await self._broadcast_host({"type": "host/workspace-removed", "workspaceId": ws_id})
                await self._broadcast_host({"type": "host/workspace-order-changed", "workspaceIds": list(self._workspace_order)})
                await send_rpc_success({"deleted": True})
            else:
                await send_rpc_error("workspace-not-found", f"Workspace {ws_id} not found")
            return

        if rpc_method in ("workspace.insertBefore", "workspace/insertBefore"):
            ws_id = req_payload.get("workspaceId")
            before_id = req_payload.get("beforeWorkspaceId")
            if ws_id in self._workspace_order:
                self._workspace_order.remove(ws_id)
                if before_id and before_id in self._workspace_order:
                    idx = self._workspace_order.index(before_id)
                    self._workspace_order.insert(idx, ws_id)
                else:
                    self._workspace_order.append(ws_id)
                await self._broadcast_host({"type": "host/workspace-order-changed", "workspaceIds": list(self._workspace_order)})
            await send_rpc_success({"workspaceIds": list(self._workspace_order)})
            return

        if rpc_method in ("workspace.insertSessionBefore", "workspace/insertSessionBefore"):
            ws_id = req_payload.get("workspaceId")
            sid = req_payload.get("sessionId")
            before_sid = req_payload.get("beforeSessionId")
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
                await send_rpc_success({"workspace": self._workspaces[ws_id]})
            else:
                await send_rpc_error("workspace-not-found", f"Workspace {ws_id} not found")
            return

        if rpc_method in ("workspace.archiveSession", "workspace/archiveSession"):
            sid = req_payload.get("sessionId")
            if sid:
                self._archived_sessions.add(sid)
                await self._broadcast_host({
                    "type": "host/archived-sessions-changed",
                    "archivedSessionIds": list(self._archived_sessions),
                })
            await send_rpc_success({"archivedSessionIds": list(self._archived_sessions)})
            return

        if rpc_method in ("workspace/files", "workspace.files"):
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
            await send_rpc_success({"files": files, "cwd": cwd})
            return

        # ── 3. Sessions Domain ──
        if rpc_method in ("session.list", "session/list", "sessions/list"):
            sessions_svc: SessionStore = self.ctx.get("sessions")
            result = []
            if sessions_svc:
                for sid, s in sessions_svc._sessions.items():
                    is_blank = (len(s.events) == 0)
                    session_cwd = (s.header.cwd or os.getcwd()).replace("\\", "/")
                    title = None
                    for ev in s.events:
                        if ev.get("type") == "session/title" and isinstance(ev.get("data"), dict):
                            title = ev["data"].get("title")

                    result.append({
                        "sessionId": sid,
                        "title": title,
                        "updatedAt": int(time.time() * 1000),
                        "running": False,
                        "blank": is_blank,
                        "parentSessionId": s.header.parent_session,
                        "cwd": session_cwd,
                        "agentPreset": s.header.agent_preset or "standard",
                        "projections": {
                            "asOfSeq": len(s.events) - 1,
                            "values": {"title": title} if title else {},
                        }
                    })
            await send_rpc_success({"items": result, "sessions": result})
            return

        if rpc_method in ("jobs.list", "jobs/list"):
            sid = req_payload.get("sessionId") or parsed_query.get("sessionId", ["default-session"])[0]
            jobs = self._background_jobs.get(sid, [])
            await send_rpc_success({"jobs": jobs, "items": jobs})
            return

        if rpc_method in ("session.create", "session/create"):
            sid = req_payload.get("sessionId") or f"session-{os.urandom(4).hex()}"
            preset = req_payload.get("agentPreset") or req_payload.get("preset", "standard")
            ws_id = req_payload.get("workspaceId")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            agent_loop = self.ctx.get("agent_loop")

            # Resolve target workspace and cwd
            target_ws = None
            if ws_id and ws_id in self._workspaces:
                target_ws = self._workspaces[ws_id]
            elif self._workspace_order:
                target_ws = self._workspaces.get(self._workspace_order[0])

            target_cwd = target_ws["path"] if target_ws else req_payload.get("cwd", os.getcwd()).replace("\\", "/")

            if sessions_svc and sid not in sessions_svc._sessions:
                s = sessions_svc.create(sid)
                s.header.cwd = target_cwd
                s.header.agent_preset = preset
            elif sessions_svc and sid in sessions_svc._sessions:
                s = sessions_svc._sessions[sid]
                s.header.cwd = target_cwd
                s.header.agent_preset = preset

            if agent_loop and sid not in self._active_sessions:
                handle = await agent_loop.create_agent(session_id=sid)
                self._active_sessions[sid] = handle

            if target_ws:
                if sid not in target_ws["sessionIds"]:
                    target_ws["sessionIds"].append(sid)
                    target_ws["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    await self._broadcast_host({
                        "type": "host/workspace-changed",
                        "workspace": target_ws,
                    })

            await self._broadcast_host({
                "type": "host/session-added",
                "sessionId": sid,
                "blank": True,
                "agentPreset": preset,
                "cwd": target_cwd,
            })

            await send_rpc_success({"success": True, "sessionId": sid, "agentPreset": preset})
            return

        if rpc_method in ("session.history", "session/history"):
            sid = req_payload.get("sessionId") or parsed_query.get("sessionId", ["default-session"])[0]
            sessions_svc: SessionStore = self.ctx.get("sessions")
            events = []
            if sessions_svc and sid in sessions_svc._sessions:
                events = sessions_svc._sessions[sid].events

            history_entries = [{"event": ev} for ev in events]
            projections_block = {
                "asOfSeq": len(events) - 1,
                "values": {},
            }
            await send_rpc_success({
                "sessionId": sid,
                "events": events,
                "entries": history_entries,
                "hasMore": False,
                "projections": projections_block,
            })
            return

        if rpc_method in ("session.rename", "session/rename"):
            sid = req_payload.get("sessionId", "default-session")
            title = req_payload.get("title", "").strip()
            sessions_svc: SessionStore = self.ctx.get("sessions")
            seq = int(time.time())
            if sessions_svc and sid in sessions_svc._sessions:
                s = sessions_svc._sessions[sid]
                s.append({
                    "type": "session/title",
                    "data": {"title": title, "source": "user"},
                    "seq": len(s.events),
                })
                seq = len(s.events) - 1

            await self._broadcast_mux({
                "type": "session/projection",
                "sessionId": sid,
                "key": "title",
                "value": title,
                "seq": seq,
            })
            await send_rpc_success({"title": title, "seq": seq})
            return

        if rpc_method in ("session.fork", "session/fork"):
            src_sid = req_payload.get("sessionId") or req_payload.get("sourceSessionId", "default-session")
            new_sid = req_payload.get("newSessionId") or f"session-fork-{os.urandom(3).hex()}"
            at_seq = req_payload.get("atSeq")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            agent_loop = self.ctx.get("agent_loop")

            if sessions_svc and src_sid in sessions_svc._sessions:
                src_session = sessions_svc._sessions[src_sid]
                new_session = sessions_svc.create(new_sid)
                new_session.header.parent_session = src_sid
                new_session.header.agent_preset = src_session.header.agent_preset
                new_session.header.cwd = src_session.header.cwd
                events_to_copy = src_session.events[:at_seq] if at_seq is not None else list(src_session.events)
                for ev in events_to_copy:
                    new_session.append(ev)

                if agent_loop:
                    handle = await agent_loop.create_agent(session_id=new_sid)
                    self._active_sessions[new_sid] = handle

                # Attach to same workspace
                for ws in self._workspaces.values():
                    if src_sid in ws["sessionIds"]:
                        if new_sid not in ws["sessionIds"]:
                            ws["sessionIds"].append(new_sid)
                            await self._broadcast_host({"type": "host/workspace-changed", "workspace": ws})
                        break

                await self._broadcast_host({
                    "type": "host/session-added",
                    "sessionId": new_sid,
                    "blank": len(events_to_copy) == 0,
                    "parentSessionId": src_sid,
                    "cwd": src_session.header.cwd,
                    "agentPreset": src_session.header.agent_preset,
                })

                await send_rpc_success({"success": True, "sessionId": new_sid, "eventCount": len(events_to_copy)})
                return
            await send_rpc_error("session-not-found", "Source session not found")
            return

        if rpc_method in ("session.prompt", "session/prompt"):
            sid = req_payload.get("sessionId", "default-session")
            mode = req_payload.get("mode", "queue")
            content_parts = req_payload.get("content", [])

            text_content = ""
            if isinstance(content_parts, str):
                text_content = content_parts
            elif isinstance(content_parts, list):
                for p in content_parts:
                    if isinstance(p, dict) and p.get("type") == "text":
                        text_content += p.get("text", "")
                    elif isinstance(p, str):
                        text_content += p

            if not text_content.strip():
                await send_rpc_error("bad-request", "Empty prompt content")
                return

            agent_loop = self.ctx.get("agent_loop")
            if not agent_loop:
                await send_rpc_error("internal", "AgentLoop service unavailable")
                return

            handle = self._active_sessions.get(sid)
            if not handle:
                handle = await agent_loop.create_agent(session_id=sid)
                self._active_sessions[sid] = handle

            agent = handle.agent
            if mode == "steer":
                agent.steer(text_content)
            else:
                agent.followup(text_content)

            await send_rpc_success({"accepted": True, "sessionId": sid})
            return

        if rpc_method in ("session.cancel", "session/cancel"):
            sid = req_payload.get("sessionId", "default-session")
            handle = self._active_sessions.get(sid)
            if handle:
                handle.agent.cancel({"kind": "user_requested"})
            await send_rpc_success({"accepted": True, "sessionId": sid})
            return

        if rpc_method in ("session.models", "session/models", "models/discover", "llm.models"):
            llm = self.ctx.get("llm")
            eff_model = llm.resolve_model() if llm else "deepseek-chat"
            groups = [{
                "id": "deepseek",
                "name": "DeepSeek Official",
                "models": [
                    {
                        "id": "deepseek-chat",
                        "name": "DeepSeek V3 (Chat)",
                        "description": "High efficiency general reasoning",
                    },
                    {
                        "id": "deepseek-reasoner",
                        "name": "DeepSeek R1 (Reasoner)",
                        "description": "Deep reasoning with explicit chain-of-thought",
                        "reasoning": {
                            "efforts": [
                                {"id": "low", "name": "Low"},
                                {"id": "medium", "name": "Medium"},
                                {"id": "high", "name": "High"},
                            ],
                            "defaultEffort": "medium",
                        },
                    },
                ],
            }]
            await send_rpc_success({
                "current": {"provider": "deepseek", "model": eff_model},
                "routable": True,
                "groups": groups,
                "failures": [],
            })
            return

        if rpc_method in ("model/set", "model.set", "session.selectModel", "session/selectModel"):
            model_name = req_payload.get("model")
            llm = self.ctx.get("llm")
            if llm and model_name:
                llm.static_model = model_name
            await send_rpc_success({"success": True, "model": model_name, "accepted": True})
            return

        # ── 4. Plan & Goal Domain ──
        if rpc_method in ("plan/set", "plan.set"):
            active = bool(req_payload.get("active", False))
            plan_mode = self.ctx.get("plan_mode")
            if plan_mode:
                plan_mode.set_active(active)
            await send_rpc_success({"success": True, "planMode": active})
            return

        if rpc_method in ("goal/action", "goal.action"):
            action = req_payload.get("action")
            goals = self.ctx.get("goals")
            g = goals.get_goal() if goals else None
            if action == "create" and goals:
                obj = req_payload.get("objective", "New Goal")
                g = goals.create_goal(objective=obj)
            elif action in ("pause", "resume", "complete") and goals and g:
                g = goals.update_goal(g.id, g.revision, action)
            await send_rpc_success({"success": True, "goal": g.to_dict() if g else None})
            return

        if rpc_method.startswith("goal.") or rpc_method.startswith("goal/"):
            action = rpc_method.split(".", 1)[-1].split("/", 1)[-1]
            goals = self.ctx.get("goals")
            g = goals.get_goal() if goals else None

            if action == "create" and goals:
                obj = req_payload.get("objective", "New Goal")
                g = goals.create_goal(objective=obj)
            elif action in ("pause", "resume", "complete") and goals and g:
                g = goals.update_goal(g.id, g.revision, action)
            elif action == "clear" and goals:
                goals.clear_goal()
                await send_rpc_success({"cleared": True})
                return

            new_ref = {"id": g.id, "revision": g.revision} if g else {"id": "g-0", "revision": 0}
            await send_rpc_success({"ref": new_ref})
            return

        # ── 5. Settings & Permissions Domain ──
        if rpc_method in ("settings.describe", "settings/describe"):
            settings_svc = self.ctx.get("settings")
            llm = self.ctx.get("llm")
            has_key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or (llm and getattr(llm, "static_api_key", None)))
            llm_info = {
                "baseUrl": llm.resolve_base_url() if llm else "https://api.deepseek.com",
                "model": llm.resolve_model() if llm else "deepseek-chat",
                "hasKey": has_key,
            }
            general_info = {"theme": "dark", "locale": "zh-CN"}
            plugins_list = [
                {"id": "shell", "name": "Persistent Terminal Shell (pwsh/bash)", "active": True},
                {"id": "agent-loop", "name": "Cordis Agent Loop & Step Driver", "active": True},
                {"id": "compaction", "name": "Context Compaction & Summary Engine", "active": True},
                {"id": "fs-search", "name": "Filesystem Search (glob/grep)", "active": True},
                {"id": "web-search", "name": "DeepSeek / Tavily Web Search Engine", "active": True},
            ]
            namespaces = [
                {
                    "ns": "llm",
                    "schema": {},
                    "value": llm_info,
                    "secrets": [{"path": ["apiKey"], "set": has_key}],
                    "applies": "live",
                    "revision": 1,
                },
                {
                    "ns": "general",
                    "schema": {},
                    "value": general_info,
                    "secrets": [],
                    "applies": "live",
                    "revision": 1,
                },
            ]
            await send_rpc_success({
                "llm": llm_info,
                "general": general_info,
                "plugins": plugins_list,
                "writable": True,
                "hasDocument": False,
                "namespaces": namespaces,
            })
            return

        if rpc_method in ("settings.update", "settings/update", "settings/save"):
            llm = self.ctx.get("llm")
            if llm:
                if req_payload.get("baseUrl"):
                    llm.static_base_url = req_payload["baseUrl"]
                if req_payload.get("apiKey"):
                    llm.static_api_key = req_payload["apiKey"]
                if req_payload.get("model"):
                    llm.static_model = req_payload["model"]
            settings_svc = self.ctx.get("settings")
            if settings_svc:
                if req_payload.get("baseUrl"):
                    settings_svc.set_setting("llm", "base_url", req_payload["baseUrl"])
                if req_payload.get("model"):
                    settings_svc.set_setting("llm", "model", req_payload["model"])
            await send_rpc_success({"success": True, "saved": True})
            return

        if rpc_method in ("permission/set", "permission.set"):
            preset = req_payload.get("preset", "workspace-write")
            await send_rpc_success({"success": True, "preset": preset})
            return

        # ── 6. Agent Presets Domain ──
        if rpc_method in ("agentPreset.list", "agentPreset/list", "presets/list"):
            presets = [
                {"id": "minimal", "name": "极简模式 (Minimal)", "description": "零额外开销，双工具"},
                {"id": "standard", "name": "标准模式 (Standard)", "description": "通用软件工程 Agent，全套工程工具"},
                {"id": "creative", "name": "创造模式 (Creative)", "description": "Cordis 双平面架构自省与扩展"},
            ]
            await send_rpc_success({"presets": presets, "items": presets})
            return

        # ── 7. Fallback / 404 ──
        await send_rpc_error("not-found", f"Unknown method or endpoint: {path}")

    async def _handle_mux_stream(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        response.write_status(200)
        response.write_header("Content-Type", "text/event-stream")
        response.write_header("Cache-Control", "no-cache")
        response.write_header("Connection", "keep-alive")
        response.write_header("Access-Control-Allow-Origin", "*")
        await response.send_headers()

        # Emit SSE comment line on open so clients see connected
        await response.write_chunk(b": connected\n\n")

        queue = asyncio.Queue()
        self._mux_clients.append(queue)
        try:
            # Emit initial session subscribed control frame for each session
            sessions_svc: SessionStore = self.ctx.get("sessions")
            if sessions_svc:
                for sid, s in sessions_svc._sessions.items():
                    sub_frame = {
                        "type": "session/subscribed",
                        "sessionId": sid,
                        "lastSeq": len(s.events) - 1,
                    }
                    await response.write_chunk(format_sse_frame(sub_frame))

            while True:
                data = await queue.get()
                await response.write_chunk(data if isinstance(data, bytes) else data.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            if queue in self._mux_clients:
                self._mux_clients.remove(queue)

    async def _handle_host_stream(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        response.write_status(200)
        response.write_header("Content-Type", "text/event-stream")
        response.write_header("Cache-Control", "no-cache")
        response.write_header("Connection", "keep-alive")
        response.write_header("Access-Control-Allow-Origin", "*")
        await response.send_headers()

        # Emit SSE comment line on open so clients see connected
        await response.write_chunk(b": connected\n\n")

        queue = asyncio.Queue()
        self._host_clients.append(queue)
        try:
            # 1. Emit initial workspace order changed frame
            order_frame = {
                "type": "host/workspace-order-changed",
                "workspaceIds": list(self._workspace_order),
            }
            await response.write_chunk(format_sse_frame(order_frame))

            # 2. Emit initial workspace changed frame for each workspace
            for ws_view in self._workspaces.values():
                ws_frame = {
                    "type": "host/workspace-changed",
                    "workspace": ws_view,
                }
                await response.write_chunk(format_sse_frame(ws_frame))

            # 3. Emit initial session added frame for each existing session
            sessions_svc: SessionStore = self.ctx.get("sessions")
            if sessions_svc:
                for sid, s in sessions_svc._sessions.items():
                    is_blank = (len(s.events) == 0)
                    session_cwd = (s.header.cwd or os.getcwd()).replace("\\", "/")
                    added_frame = {
                        "type": "host/session-added",
                        "sessionId": sid,
                        "blank": is_blank,
                        "cwd": session_cwd,
                        "agentPreset": s.header.agent_preset or "standard",
                    }
                    await response.write_chunk(format_sse_frame(added_frame))

            while True:
                data = await queue.get()
                await response.write_chunk(data if isinstance(data, bytes) else data.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            if queue in self._host_clients:
                self._host_clients.remove(queue)
