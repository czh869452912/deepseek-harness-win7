"""
API Proxy Bridge Plugin (`@deepseek-ai/dsh-apiproxy`).
Provides `/api/...` HTTP endpoints and SSE event streaming for the Web GUI.
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional
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
        self._sse_clients: List[asyncio.Queue] = []
        self._active_sessions: Dict[str, Any] = {}

    def apply(self, ctx: Any) -> None:
        web_server: WebServerService = ctx.get("web_server")
        if not web_server:
            return

        # Register /api prefix routes
        disposer = web_server.register("prefix", "/api", self._handle_api_request)
        if hasattr(ctx, "effect"):
            ctx.effect(disposer)

        # Hook session events to broadcast via SSE
        ctx.on("session/event", self._on_session_event)
        ctx.on("session/append", self._on_session_event)
        ctx.on("session/chunk", self._on_session_chunk)
        ctx.on("assistant/chunk", self._on_assistant_chunk)
        ctx.on("agent/status", self._on_agent_status)
        ctx.on("goal/changed", self._on_goal_changed)
        ctx.on("goal/change", self._on_goal_changed)

    async def _broadcast_sse(self, event_type: str, data: Any) -> None:
        try:
            payload = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            for q in list(self._sse_clients):
                try:
                    await q.put(payload)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_session_chunk(self, *args: Any, **kwargs: Any) -> None:
        try:
            chunk = None
            if len(args) >= 2:
                chunk = args[1]
            elif len(args) == 1:
                chunk = args[0]
            if isinstance(chunk, dict):
                asyncio.create_task(self._broadcast_sse("session/chunk", chunk))
        except Exception:
            pass

    def _on_assistant_chunk(self, *args: Any, **kwargs: Any) -> None:
        try:
            chunk = args[0] if args else {}
            if isinstance(chunk, dict):
                asyncio.create_task(self._broadcast_sse("assistant/chunk", chunk))
        except Exception:
            pass

    def _on_session_event(self, *args: Any, **kwargs: Any) -> None:
        try:
            event = None
            if len(args) >= 2:
                event = args[1]
            elif len(args) == 1:
                event = args[0]
            if isinstance(event, dict):
                asyncio.create_task(self._broadcast_sse("session/event", event))
        except Exception:
            pass

    def _on_agent_status(self, *args: Any, **kwargs: Any) -> None:
        try:
            payload = args[0] if args else {}
            if isinstance(payload, dict):
                status = payload.get("status")
                agent = payload.get("agent")
                sid = getattr(agent, "session_id", None) if agent else None
                if not sid and agent and hasattr(agent, "session"):
                    sid = getattr(agent.session, "id", None)
                asyncio.create_task(self._broadcast_sse("agent/status", {
                    "status": str(status) if status is not None else "idle",
                    "sessionId": sid,
                }))
            else:
                asyncio.create_task(self._broadcast_sse("agent/status", {"status": str(payload)}))
        except Exception:
            pass

    def _on_goal_changed(self, *args: Any, **kwargs: Any) -> None:
        try:
            goal = args[0] if args else None
            goal_data = goal.to_dict() if (goal and hasattr(goal, "to_dict")) else goal
            asyncio.create_task(self._broadcast_sse("goal/changed", {"goal": goal_data}))
        except Exception:
            pass

    async def _handle_api_request(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        path = request.get("path", "")
        method = request.get("method", "GET")

        # CORS headers for web development
        response.write_header("Access-Control-Allow-Origin", "*")
        response.write_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.write_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

        if method == "OPTIONS":
            response.write_status(204)
            await response.finish()
            return

        if path == "/api/session/events":
            await self._handle_sse_stream(request, response)
            return

        # JSON response helper
        async def send_json(data: Any, status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            response.write_status(status)
            response.write_header("Content-Type", "application/json; charset=utf-8")
            response.write_body(body)
            await response.finish()

        parsed_query = urllib.parse.parse_qs(request.get("query", ""))
        body_json = {}
        if request.get("body"):
            try:
                body_json = json.loads(request["body"].decode("utf-8"))
            except Exception:
                pass

        # 1. /api/status
        if path == "/api/status":
            llm = self.ctx.get("llm")
            goals = self.ctx.get("goals")
            plan_mode = self.ctx.get("plan_mode")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            curr_goal = goals.get_goal() if goals else None
            plan_active = plan_mode.is_active() if plan_mode else False

            effective_model = llm.resolve_model() if llm else "unknown"
            effective_base_url = llm.resolve_base_url() if llm else "https://api.deepseek.com/v1"

            await send_json({
                "status": "ready",
                "cwd": os.getcwd(),
                "model": effective_model,
                "baseUrl": effective_base_url,
                "planMode": plan_active,
                "goal": curr_goal.to_dict() if curr_goal else None,
                "sessionsCount": len(sessions_svc._sessions) if sessions_svc else 0,
            })
            return

        # 2. /api/presets/list
        if path == "/api/presets/list":
            presets = [
                {"id": "minimal", "name": "极简模式 (Minimal)", "description": "零额外开销，双工具"},
                {"id": "standard", "name": "标准模式 (Standard)", "description": "通用软件工程 Agent，全套工程工具"},
                {"id": "creative", "name": "创造模式 (Creative)", "description": "Cordis 双平面架构自省与扩展"},
            ]
            await send_json({"presets": presets})
            return

        # 3. /api/session/list
        if path == "/api/session/list":
            sessions_svc: SessionStore = self.ctx.get("sessions")
            result = []
            if sessions_svc:
                for sid, s in sessions_svc._sessions.items():
                    result.append({
                        "id": sid,
                        "createdAt": s.header.created_at,
                        "eventCount": len(s.events),
                        "preset": s.header.agent_preset or "standard",
                    })
            await send_json({"sessions": result})
            return

        # 4. /api/session/create
        if path == "/api/session/create" and method == "POST":
            sid = body_json.get("sessionId") or f"session-{len(self._active_sessions)+1}"
            preset = body_json.get("preset", "standard")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            agent_loop = self.ctx.get("agent_loop")

            if sessions_svc and sid not in sessions_svc._sessions:
                s = sessions_svc.create(sid)
                s.header.agent_preset = preset
            if agent_loop and sid not in self._active_sessions:
                handle = await agent_loop.create_agent(session_id=sid)
                self._active_sessions[sid] = handle

            await send_json({"success": True, "sessionId": sid, "preset": preset})
            return

        # 5. /api/session/fork
        if path == "/api/session/fork" and method == "POST":
            src_sid = body_json.get("sourceSessionId", "default-session")
            new_sid = body_json.get("newSessionId") or f"session-fork-{os.urandom(3).hex()}"
            cutoff = body_json.get("cutoffIndex")
            sessions_svc: SessionStore = self.ctx.get("sessions")
            agent_loop = self.ctx.get("agent_loop")

            if sessions_svc and src_sid in sessions_svc._sessions:
                src_session = sessions_svc._sessions[src_sid]
                new_session = sessions_svc.create(new_sid)
                new_session.header.agent_preset = src_session.header.agent_preset
                events_to_copy = src_session.events[:cutoff] if cutoff is not None else list(src_session.events)
                for ev in events_to_copy:
                    new_session.append(ev)

                if agent_loop:
                    handle = await agent_loop.create_agent(session_id=new_sid)
                    self._active_sessions[new_sid] = handle

                await send_json({"success": True, "sessionId": new_sid, "eventCount": len(events_to_copy)})
                return
            await send_json({"error": "Source session not found"}, 404)
            return

        # 6. /api/session/history
        if path == "/api/session/history":
            sid = parsed_query.get("sessionId", ["default-session"])[0]
            sessions_svc: SessionStore = self.ctx.get("sessions")
            events = []
            if sessions_svc and sid in sessions_svc._sessions:
                events = sessions_svc._sessions[sid].events
            await send_json({"sessionId": sid, "events": events})
            return

        # 7. /api/agent/prompt
        if path == "/api/agent/prompt" and method == "POST":
            sid = body_json.get("sessionId", "default-session")
            content = body_json.get("content", "").strip()
            if not content:
                await send_json({"error": "Empty prompt content"}, 400)
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
            agent.followup(content)

            await send_json({"success": True, "status": "queued", "sessionId": sid})
            return

        # 8. /api/agent/cancel
        if path == "/api/agent/cancel" and method == "POST":
            sid = body_json.get("sessionId", "default-session")
            handle = self._active_sessions.get(sid)
            if handle:
                handle.agent.cancel({"kind": "user_requested"})
            await send_json({"success": True, "sessionId": sid})
            return

        # 9. /api/plan/set
        if path == "/api/plan/set" and method == "POST":
            active = bool(body_json.get("active", False))
            plan_mode = self.ctx.get("plan_mode")
            if plan_mode:
                plan_mode.set_active(active)
            await send_json({"success": True, "planMode": active})
            return

        # 10. /api/goal/action
        if path == "/api/goal/action" and method == "POST":
            action = body_json.get("action")
            goals = self.ctx.get("goals")
            if not goals:
                await send_json({"error": "GoalService unavailable"}, 500)
                return

            g = goals.get_goal()
            if action == "create":
                obj = body_json.get("objective", "New Goal")
                g = goals.create_goal(objective=obj)
            elif action in ("pause", "resume", "complete") and g:
                g = goals.update_goal(g.id, g.revision, action)

            await send_json({"success": True, "goal": g.to_dict() if g else None})
            return

        # 11. /api/model/set
        if path == "/api/model/set" and method == "POST":
            model_name = body_json.get("model")
            llm = self.ctx.get("llm")
            if llm and model_name:
                llm.static_model = model_name
            await send_json({"success": True, "model": model_name})
            return

        # 12. /api/settings/save
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
                if body_json.get("general"):
                    for k, v in body_json["general"].items():
                        settings_svc.set_setting("general", k, v)

            await send_json({"success": True, "saved": True})
            return

        # 13. /api/settings/describe
        if path == "/api/settings/describe":
            llm = self.ctx.get("llm")
            settings_svc = self.ctx.get("settings")
            loader = self.ctx.get("loader")

            plugins_list = []
            if loader and hasattr(loader, "list_plugins"):
                for p in loader.list_plugins():
                    plugins_list.append({"id": p.id, "name": getattr(p, "name", p.id), "active": True})
            else:
                plugins_list = [
                    {"id": "shell", "name": "Persistent Terminal Shell (pwsh/bash)", "active": True},
                    {"id": "agent-loop", "name": "Cordis Agent Loop & Step Driver", "active": True},
                    {"id": "compaction", "name": "Context Compaction & Summary Engine", "active": True},
                    {"id": "fs-search", "name": "Filesystem Search (glob/grep)", "active": True},
                    {"id": "web-search", "name": "DeepSeek / Tavily Web Search Engine", "active": True},
                ]

            general_settings = {
                "busyEnter": "queue",
                "theme": "dark",
                "fontSize": "13px",
            }
            if settings_svc:
                g_cfg = settings_svc.get_section("general") or {}
                general_settings.update(g_cfg)

            await send_json({
                "llm": {
                    "baseUrl": llm.resolve_base_url() if llm and hasattr(llm, "resolve_base_url") else "https://api.deepseek.com",
                    "model": llm.resolve_model() if llm and hasattr(llm, "resolve_model") else "deepseek-v4-flash",
                    "hasKey": bool((llm and getattr(llm, "static_api_key", None)) or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")),
                },
                "general": general_settings,
                "plugins": plugins_list,
            })
            return

        # 14. /api/workspace/files (for @file mention suggestions)
        if path == "/api/workspace/files":
            cwd = os.getcwd()
            ignore_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", ".gemini", ".idea", ".vscode"}
            files = []
            for root, dirs, filenames in os.walk(cwd):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                rel_dir = os.path.relpath(root, cwd)
                for f in filenames:
                    if f.startswith(".") or f.endswith(".pyc"):
                        continue
                    rel_path = os.path.normpath(f if rel_dir == "." else os.path.join(rel_dir, f)).replace("\\", "/")
                    files.append({
                        "path": rel_path,
                        "name": f,
                        "ext": os.path.splitext(f)[1].lstrip("."),
                    })
                    if len(files) >= 300:
                        break
                if len(files) >= 300:
                    break
            await send_json({"files": files, "cwd": cwd})
            return

        # 15. /api/models/discover
        if path == "/api/models/discover" and method == "POST":
            llm = self.ctx.get("llm")
            base_url = body_json.get("baseUrl") or (llm.resolve_base_url() if llm else "https://api.deepseek.com")
            api_key = body_json.get("apiKey") or (llm.resolve_api_key() if llm else "")

            url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    models_raw = resp_data.get("data", [])
                    models = [m.get("id") for m in models_raw if isinstance(m, dict) and "id" in m]
                    await send_json({"success": True, "models": models or ["deepseek-chat", "deepseek-reasoner"]})
                    return
            except Exception as ex:
                await send_json({"success": False, "error": str(ex), "models": ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"]})
                return

        # 16. /api/permission/set
        if path == "/api/permission/set" and method == "POST":
            preset = body_json.get("preset", "workspace-write")
            # Store in session or ctx
            await send_json({"success": True, "preset": preset})
            return

        # 17. /api/jobs/list
        if path == "/api/jobs/list":
            # List current active jobs
            agent_loop = self.ctx.get("agent_loop")
            active_count = len(getattr(agent_loop, "_active_tasks", [])) if agent_loop else 0
            jobs = []
            if active_count > 0:
                jobs.append({
                    "id": "agent-driver",
                    "kind": "agent-turn",
                    "label": "Agent Execution Loop",
                    "status": "running",
                    "startedAt": int(os.path.getctime(os.getcwd()) if os.path.exists(os.getcwd()) else 0) * 1000,
                })
            await send_json({"jobs": jobs})
            return

        # Not found
        await send_json({"error": f"API route not found: {path}"}, 404)

    async def _handle_sse_stream(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        response.write_status(200)
        response.write_header("Content-Type", "text/event-stream")
        response.write_header("Cache-Control", "no-cache")
        response.write_header("Connection", "keep-alive")
        response.write_header("Access-Control-Allow-Origin", "*")
        await response.send_headers()

        queue = asyncio.Queue()
        self._sse_clients.append(queue)

        try:
            # Send initial ping
            await response.write_chunk(b"event: connected\ndata: {}\n\n")
            while True:
                data = await queue.get()
                await response.write_chunk(data.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            if queue in self._sse_clients:
                self._sse_clients.remove(queue)
