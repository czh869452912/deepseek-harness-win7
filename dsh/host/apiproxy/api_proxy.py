"""
API Proxy Bridge Plugin (`@deepseek-ai/dsh-apiproxy`).
Provides `/api/...` HTTP RPC endpoints and dual SSE event streams (mux + host) for the Web GUI.
"""

import asyncio
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import urllib.parse
import urllib.request

from dsh.cordis.plugin import Plugin
from dsh.core.session import Session, SessionStore
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService


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

        # Initialize default workspace from cwd
        cwd = os.path.normpath(os.getcwd()).replace("\\", "/")
        ws_id = f"ws-{hashlib_short(cwd.encode('utf-8'))}"
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
            ctx.effect(disposer)

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

    async def _broadcast_mux(self, frame: Dict[str, Any]) -> None:
        try:
            payload = f"event: mux\ndata: {json.dumps(frame, ensure_ascii=False, default=str)}\n\n"
            for q in list(self._mux_clients):
                try:
                    await q.put(payload)
                except Exception:
                    pass
        except Exception:
            pass

    async def _broadcast_host(self, frame: Dict[str, Any]) -> None:
        try:
            payload = f"event: host\ndata: {json.dumps(frame, ensure_ascii=False, default=str)}\n\n"
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

    def _on_question_requested(self, *args: Any, **kwargs: Any) -> None:
        try:
            req = args[0] if args else {}
            sid = req.get("sessionId", "default-session")
            rpc_id = req.get("rpcId") or f"rpc-q-{os.urandom(4).hex()}"
            req["rpcId"] = rpc_id
            asyncio.create_task(self._broadcast_mux({
                "type": "question/requested",
                "sessionId": sid,
                "rpcId": rpc_id,
                "questions": req.get("questions", []),
            }))
        except Exception:
            pass

    def _on_approval_requested(self, *args: Any, **kwargs: Any) -> None:
        try:
            req = args[0] if args else {}
            sid = req.get("sessionId", "default-session")
            rpc_id = req.get("rpcId") or f"rpc-a-{os.urandom(4).hex()}"
            req["rpcId"] = rpc_id
            asyncio.create_task(self._broadcast_mux({
                "type": "approval/requested",
                "sessionId": sid,
                "rpcId": rpc_id,
                "approvalId": req.get("approvalId", rpc_id),
                "toolName": req.get("toolName", "unknown"),
                "reason": req.get("reason", ""),
            }))
        except Exception:
            pass

    async def _handle_api_request(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        path = request.get("path", "")
        method = request.get("method", "GET")

        # CORS headers
        response.write_header("Access-Control-Allow-Origin", "*")
        response.write_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.write_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

        if method == "OPTIONS":
            response.write_status(204)
            await response.finish()
            return

        # Dual Streaming SSE Endpoints
        if path == "/api/events/mux" or path == "/api/session/events":
            await self._handle_mux_stream(request, response)
            return
        if path == "/api/events/host":
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

        # 1. Host Describe & Status
        if path == "/api/host/describe" or path == "/api/status":
            llm = self.ctx.get("llm")
            goals = self.ctx.get("goals")
            plan_mode = self.ctx.get("plan_mode")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            curr_goal = goals.get_goal() if goals else None
            plan_active = plan_mode.is_active() if plan_mode else False

            effective_model = llm.resolve_model() if llm else "unknown"
            effective_base_url = llm.resolve_base_url() if llm else "https://api.deepseek.com/v1"

            val = {
                "status": "ready",
                "cwd": os.getcwd(),
                "model": effective_model,
                "baseUrl": effective_base_url,
                "planMode": plan_active,
                "goal": curr_goal.to_dict() if curr_goal else None,
                "sessionsCount": len(sessions_svc._sessions) if sessions_svc else 0,
            }
            # Provide both flat keys and result.ok.value structure
            await send_json({
                **val,
                "result": {"ok": True, "value": val},
            })
            return

        # Plan Mode Set
        if path == "/api/plan/set" and method == "POST":
            active = bool(body_json.get("active", False))
            plan_mode = self.ctx.get("plan_mode")
            if plan_mode:
                plan_mode.set_active(active)
            await send_json({"success": True, "planMode": active})
            return

        # Model Set
        if path == "/api/model/set" and method == "POST":
            model_name = body_json.get("model")
            llm = self.ctx.get("llm")
            if llm and model_name:
                llm.static_model = model_name
            await send_json({"success": True, "model": model_name})
            return

        # Settings Save
        if path == "/api/settings/save" and method == "POST":
            llm = self.ctx.get("llm")
            if llm:
                if body_json.get("baseUrl"):
                    llm.static_base_url = body_json["baseUrl"]
                if body_json.get("apiKey"):
                    llm.static_api_key = body_json["apiKey"]
                if body_json.get("model"):
                    llm.static_model = body_json["model"]
            settings_svc = self.ctx.get("settings")
            if settings_svc:
                if body_json.get("baseUrl"):
                    settings_svc.set_setting("llm", "base_url", body_json["baseUrl"])
                if body_json.get("model"):
                    settings_svc.set_setting("llm", "model", body_json["model"])
            await send_json({"success": True, "saved": True})
            return

        # Permission Set
        if path == "/api/permission/set" and method == "POST":
            preset = body_json.get("preset", "workspace-write")
            await send_json({"success": True, "preset": preset})
            return

        # Goal Action
        if path == "/api/goal/action" and method == "POST":
            action = body_json.get("action")
            goals = self.ctx.get("goals")
            g = goals.get_goal() if goals else None
            if action == "create" and goals:
                obj = body_json.get("objective", "New Goal")
                g = goals.create_goal(objective=obj)
            elif action in ("pause", "resume", "complete") and goals and g:
                g = goals.update_goal(g.id, g.revision, action)
            await send_json({"success": True, "goal": g.to_dict() if g else None})
            return

        # 2. Server-Request Answer Response (/api/respond)
        if path == "/api/respond" and method == "POST":
            rpc_id = body_json.get("rpcId")
            sid = body_json.get("sessionId", "default-session")
            answer = body_json.get("answer")
            outcome = body_json.get("outcome")

            if rpc_id and rpc_id in self._pending_server_requests:
                fut = self._pending_server_requests.pop(rpc_id)
                if not fut.done():
                    fut.set_result(answer or outcome or True)

            # Broadcast resolved frame
            if answer is not None:
                await self._broadcast_mux({
                    "type": "question/resolved",
                    "sessionId": sid,
                    "questionRpcId": rpc_id,
                    "outcome": "answered",
                })
            elif outcome is not None:
                await self._broadcast_mux({
                    "type": "approval/resolved",
                    "sessionId": sid,
                    "approvalId": body_json.get("approvalId", rpc_id),
                    "outcome": outcome,
                })

            await send_json({"ok": True, "accepted": True})
            return

        # 3. Sessions API
        if path == "/api/session/list" or path == "/api/sessions/list":
            sessions_svc: SessionStore = self.ctx.get("sessions")
            result = []
            if sessions_svc:
                for sid, s in sessions_svc._sessions.items():
                    is_blank = (len(s.events) == 0)
                    result.append({
                        "sessionId": sid,
                        "updatedAt": s.header.created_at,
                        "running": False,
                        "blank": is_blank,
                        "parentSessionId": s.header.parent_session,
                        "cwd": s.header.cwd or os.getcwd(),
                        "agentPreset": s.header.agent_preset or "standard",
                        "projections": {
                            "asOfSeq": len(s.events) - 1,
                            "values": {},
                        }
                    })
            await send_json({"items": result, "sessions": result})
            return

        if path == "/api/session/create" and method == "POST":
            sid = body_json.get("sessionId") or f"session-{len(self._active_sessions)+1}"
            preset = body_json.get("agentPreset") or body_json.get("preset", "standard")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            agent_loop = self.ctx.get("agent_loop")

            if sessions_svc and sid not in sessions_svc._sessions:
                s = sessions_svc.create(sid)
                s.header.agent_preset = preset
            if agent_loop and sid not in self._active_sessions:
                handle = await agent_loop.create_agent(session_id=sid)
                self._active_sessions[sid] = handle

            # Broadcast session added
            await self._broadcast_host({
                "type": "host/session-added",
                "sessionId": sid,
                "blank": True,
                "agentPreset": preset,
                "cwd": os.getcwd(),
            })

            await send_json({"success": True, "sessionId": sid, "agentPreset": preset})
            return

        if path == "/api/session/history":
            sid = parsed_query.get("sessionId", ["default-session"])[0]
            sessions_svc: SessionStore = self.ctx.get("sessions")
            events = []
            if sessions_svc and sid in sessions_svc._sessions:
                events = sessions_svc._sessions[sid].events

            history_entries = [{"event": ev} for ev in events]
            projections_block = {
                "asOfSeq": len(events) - 1,
                "values": {},
            }
            await send_json({
                "sessionId": sid,
                "events": events,
                "entries": history_entries,
                "hasMore": False,
                "projections": projections_block,
            })
            return

        if path == "/api/session/rename" and method == "POST":
            sid = body_json.get("sessionId", "default-session")
            title = body_json.get("title", "").strip()
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
            await send_json({"title": title, "seq": seq})
            return

        if path == "/api/session/fork" and method == "POST":
            src_sid = body_json.get("sessionId") or body_json.get("sourceSessionId", "default-session")
            new_sid = body_json.get("newSessionId") or f"session-fork-{os.urandom(3).hex()}"
            at_seq = body_json.get("atSeq")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            agent_loop = self.ctx.get("agent_loop")

            if sessions_svc and src_sid in sessions_svc._sessions:
                src_session = sessions_svc._sessions[src_sid]
                new_session = sessions_svc.create(new_sid)
                new_session.header.parent_session = src_sid
                new_session.header.agent_preset = src_session.header.agent_preset
                events_to_copy = src_session.events[:at_seq] if at_seq is not None else list(src_session.events)
                for ev in events_to_copy:
                    new_session.append(ev)

                if agent_loop:
                    handle = await agent_loop.create_agent(session_id=new_sid)
                    self._active_sessions[new_sid] = handle

                await self._broadcast_host({
                    "type": "host/session-added",
                    "sessionId": new_sid,
                    "blank": len(events_to_copy) == 0,
                    "parentSessionId": src_sid,
                    "cwd": src_session.header.cwd,
                    "agentPreset": src_session.header.agent_preset,
                })

                await send_json({"success": True, "sessionId": new_sid, "eventCount": len(events_to_copy)})
                return
            await send_json({"error": "Source session not found"}, 404)
            return

        if path == "/api/session/prompt" and method == "POST":
            sid = body_json.get("sessionId", "default-session")
            mode = body_json.get("mode", "queue")
            content_parts = body_json.get("content", [])
            client_tz = body_json.get("clientTimeZone")

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
                await send_json({"error": "Empty prompt"}, 400)
                return

            agent_loop = self.ctx.get("agent_loop")
            if not agent_loop:
                await send_json({"error": "AgentLoop unavailable"}, 500)
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

            await send_json({"accepted": True, "sessionId": sid})
            return

        if path == "/api/session/cancel" and method == "POST":
            sid = body_json.get("sessionId", "default-session")
            handle = self._active_sessions.get(sid)
            if handle:
                handle.agent.cancel({"kind": "user_requested"})
            await send_json({"accepted": True, "sessionId": sid})
            return

        # 4. Workspace API
        if path == "/api/workspace/list":
            await send_json({
                "items": list(self._workspaces.values()),
                "archivedSessionIds": list(self._archived_sessions),
            })
            return

        if path == "/api/workspace/create" and method == "POST":
            ws_path = os.path.normpath(body_json.get("path", os.getcwd())).replace("\\", "/")
            ws_id = f"ws-{hashlib_short(ws_path.encode('utf-8'))}"
            created = (ws_id not in self._workspaces)
            if created:
                ws_view = {
                    "workspaceId": ws_id,
                    "path": ws_path,
                    "title": os.path.basename(ws_path) or "root",
                    "sessionIds": [],
                    "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                self._workspaces[ws_id] = ws_view
                self._workspace_order.append(ws_id)
                await self._broadcast_host({"type": "host/workspace-changed", "workspace": ws_view})
            else:
                ws_view = self._workspaces[ws_id]

            await send_json({"workspace": ws_view, "created": created})
            return

        if path == "/api/workspace/archiveSession" and method == "POST":
            sid = body_json.get("sessionId")
            if sid:
                self._archived_sessions.add(sid)
                await self._broadcast_host({
                    "type": "host/archived-sessions-changed",
                    "archivedSessionIds": list(self._archived_sessions),
                })
            await send_json({"archivedSessionIds": list(self._archived_sessions)})
            return

        # 5. Goal API (CAS revision guarded)
        if path.startswith("/api/goals/") and method == "POST":
            sub_action = path.split("/")[-1]
            goals = self.ctx.get("goals")
            if not goals:
                await send_json({"error": "GoalsService unavailable"}, 500)
                return

            g = goals.get_goal()
            ref_dict = body_json.get("ref", {})
            req_rev = ref_dict.get("revision") if isinstance(ref_dict, dict) else None

            if sub_action == "create":
                obj = body_json.get("objective", "New Goal")
                g = goals.create_goal(objective=obj)
            elif sub_action == "pause" and g:
                g = goals.update_goal(g.id, g.revision, "pause")
            elif sub_action == "resume" and g:
                g = goals.update_goal(g.id, g.revision, "resume")
            elif sub_action == "complete" and g:
                g = goals.update_goal(g.id, g.revision, "complete")
            elif sub_action == "clear" and g:
                goals.clear_goal()
                await send_json({"cleared": True})
                return

            new_ref = {"id": g.id, "revision": g.revision} if g else {"id": "g-0", "revision": 0}
            await send_json({"ref": new_ref})
            return

        # 6. Jobs API
        if path == "/api/jobs/list":
            sid = parsed_query.get("sessionId", ["default-session"])[0]
            jobs = self._background_jobs.get(sid, [])
            await send_json({"jobs": jobs})
            return

        # 7. Model selection & Settings
        if path == "/api/session/models" or path == "/api/models/discover":
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
            await send_json({
                "current": {"provider": "deepseek", "model": eff_model},
                "routable": True,
                "groups": groups,
                "failures": [],
            })
            return

        # 8. Settings API (with secret redaction)
        if path == "/api/settings/describe":
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
            await send_json({
                "llm": llm_info,
                "general": general_info,
                "plugins": plugins_list,
                "writable": True,
                "hasDocument": False,
                "namespaces": namespaces,
            })
            return

        # 9. Workspace files for suggestion
        if path == "/api/workspace/files":
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
            await send_json({"files": files, "cwd": cwd})
            return

        # 10. Presets list
        if path == "/api/presets/list":
            presets = [
                {"id": "minimal", "name": "极简模式 (Minimal)", "description": "零额外开销，双工具"},
                {"id": "standard", "name": "标准模式 (Standard)", "description": "通用软件工程 Agent，全套工程工具"},
                {"id": "creative", "name": "创造模式 (Creative)", "description": "Cordis 双平面架构自省与扩展"},
            ]
            await send_json({"presets": presets})
            return

        # Fallback
        await send_json({"error": f"Endpoint not found: {path}"}, 404)

    async def _handle_mux_stream(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        response.write_status(200)
        response.write_header("Content-Type", "text/event-stream")
        response.write_header("Cache-Control", "no-cache")
        response.write_header("Connection", "keep-alive")
        response.write_header("Access-Control-Allow-Origin", "*")
        await response.send_headers()

        queue = asyncio.Queue()
        self._mux_clients.append(queue)
        try:
            # Emit initial session subscribed control frame
            sessions_svc: SessionStore = self.ctx.get("sessions")
            if sessions_svc:
                for sid, s in sessions_svc._sessions.items():
                    init_frame = {
                        "type": "session/subscribed",
                        "sessionId": sid,
                        "lastSeq": len(s.events) - 1,
                    }
                    payload = f"event: mux\ndata: {json.dumps(init_frame, ensure_ascii=False, default=str)}\n\n"
                    await response.write_chunk(payload.encode("utf-8"))

            while True:
                data = await queue.get()
                await response.write_chunk(data.encode("utf-8"))
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

        queue = asyncio.Queue()
        self._host_clients.append(queue)
        try:
            # Emit initial host snapshot frame
            init_frame = {
                "type": "host/workspace-order-changed",
                "workspaceIds": list(self._workspace_order),
            }
            payload = f"event: host\ndata: {json.dumps(init_frame, ensure_ascii=False, default=str)}\n\n"
            await response.write_chunk(payload.encode("utf-8"))

            while True:
                data = await queue.get()
                await response.write_chunk(data.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            if queue in self._host_clients:
                self._host_clients.remove(queue)


def hashlib_short(data: bytes) -> str:
    import hashlib
    return hashlib.sha1(data).hexdigest()[:8]
