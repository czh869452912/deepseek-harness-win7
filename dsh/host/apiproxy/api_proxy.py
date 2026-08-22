"""
API Proxy Bridge Plugin (`@deepseek-ai/dsh-apiproxy`).
Provides `/api/...` HTTP RPC endpoints and dual SSE event streams (mux + host) for the Web GUI.
Aligned 1:1 with official DeepSeek Harness ApiProxy & Fetch carrier protocol.
"""

import asyncio
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Set
import urllib.parse

from dsh.cordis.plugin import Plugin
from dsh.core.session import SessionStore
from dsh.host.apiproxy.api import (
    AgentPresetsDomainHandler,
    ApprovalsDomainHandler,
    CredentialsDomainHandler,
    DownloadsDomainHandler,
    GoalsDomainHandler,
    HostDomainHandler,
    JobsDomainHandler,
    LLMDomainHandler,
    QuestionsDomainHandler,
    SessionSearchDomainHandler,
    SessionsDomainHandler,
    SettingsDomainHandler,
    SkillsDomainHandler,
    SubagentsDomainHandler,
    WorkspaceDomainHandler,
    format_sse_frame,
)
from dsh.host.apiproxy.fetch import normalize_rpc_method
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService


def hashlib_short(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:8]


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

        # Domain handlers
        self.agent_presets_handler: Optional[AgentPresetsDomainHandler] = None
        self.approvals_handler: Optional[ApprovalsDomainHandler] = None
        self.credentials_handler: Optional[CredentialsDomainHandler] = None
        self.downloads_handler: Optional[DownloadsDomainHandler] = None
        self.goals_handler: Optional[GoalsDomainHandler] = None
        self.host_handler: Optional[HostDomainHandler] = None
        self.jobs_handler: Optional[JobsDomainHandler] = None
        self.llm_handler: Optional[LLMDomainHandler] = None
        self.questions_handler: Optional[QuestionsDomainHandler] = None
        self.session_search_handler: Optional[SessionSearchDomainHandler] = None
        self.sessions_handler: Optional[SessionsDomainHandler] = None
        self.settings_handler: Optional[SettingsDomainHandler] = None
        self.skills_handler: Optional[SkillsDomainHandler] = None
        self.subagents_handler: Optional[SubagentsDomainHandler] = None
        self.workspace_handler: Optional[WorkspaceDomainHandler] = None

    def _init_domain_handlers(self) -> None:
        self.agent_presets_handler = AgentPresetsDomainHandler(self.ctx)
        self.approvals_handler = ApprovalsDomainHandler(self.ctx, self._pending_server_requests, self._broadcast_mux)
        self.credentials_handler = CredentialsDomainHandler(self.ctx)
        self.downloads_handler = DownloadsDomainHandler(self.ctx)
        self.goals_handler = GoalsDomainHandler(self.ctx)
        self.host_handler = HostDomainHandler(self.ctx, self._active_sessions)
        self.jobs_handler = JobsDomainHandler(self.ctx, self._background_jobs)
        self.llm_handler = LLMDomainHandler(self.ctx)
        self.questions_handler = QuestionsDomainHandler(self.ctx, self._pending_server_requests, self._broadcast_mux)
        self.session_search_handler = SessionSearchDomainHandler(self.ctx)
        self.sessions_handler = SessionsDomainHandler(self.ctx, self._active_sessions, self._broadcast_mux, self._broadcast_host, self._workspaces)
        self.settings_handler = SettingsDomainHandler(self.ctx)
        self.skills_handler = SkillsDomainHandler(self.ctx)
        self.subagents_handler = SubagentsDomainHandler(self.ctx)
        self.workspace_handler = WorkspaceDomainHandler(self.ctx, self._workspaces, self._workspace_order, self._archived_sessions, self._active_sessions, self._broadcast_host)

    def apply(self, ctx: Any) -> None:
        web_server: WebServerService = ctx.get("web_server") or ctx.get("webServer")
        if not web_server:
            return

        self._init_domain_handlers()

        sessions_svc: SessionStore = ctx.get("sessions")
        cwd = os.path.normpath(os.getcwd()).replace("\\", "/")
        ws_id = f"ws-{hashlib_short(cwd.encode('utf-8'))}"

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

        disposer = web_server.register("prefix", "/api", self._handle_api_request)
        if hasattr(ctx, "effect"):
            ctx.effect(lambda: disposer)

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
            if self.questions_handler:
                self.questions_handler.request_question(q)
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

        response.write_header("Access-Control-Allow-Origin", "*")
        response.write_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        response.write_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

        if method == "OPTIONS":
            response.write_status(204)
            await response.finish()
            return

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

        # /api/respond
        if path == "/api/respond" and method == "POST":
            res = await self.approvals_handler.handle_respond(body_json)
            await send_json(res)
            return

        # /api/session.export
        if path in ("/api/session.export", "/api/session/export"):
            sid = parsed_query.get("sessionId", [None])[0] or req_payload.get("sessionId", "default-session")
            fmt = parsed_query.get("format", ["zip"])[0]
            exported = self.downloads_handler.export_session(sid, fmt)
            response.write_status(200)
            response.write_header("Content-Type", exported["content_type"])
            response.write_header("Content-Disposition", f'attachment; filename="{exported["filename"]}"')
            response.write_body(exported["body"] if isinstance(exported["body"], bytes) else exported["body"].encode("utf-8"))
            await response.finish()
            return

        rpc_method = normalize_rpc_method(path)

        try:
            # Dispatch to domain handlers
            if rpc_method in ("host.describe", "host/describe", "status"):
                res = await self.host_handler.describe_host(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("host.pickDirectory", "host/pickDirectory"):
                res = await self.host_handler.pick_directory(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("host.listDirectory", "host/listDirectory"):
                res = await self.host_handler.list_directory({**req_payload, "path": req_payload.get("path") or parsed_query.get("path", [None])[0]})
                await send_rpc_success(res)
                return

            if rpc_method in ("host.createDirectory", "host/createDirectory"):
                res = await self.host_handler.create_directory(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("host.openPath", "host/openPath"):
                res = await self.host_handler.open_path(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("workspace.list", "workspace/list"):
                res = await self.workspace_handler.list_workspaces(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("workspace.create", "workspace/create"):
                res = await self.workspace_handler.create_workspace(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("workspace.rename", "workspace/rename"):
                res = await self.workspace_handler.rename_workspace(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("workspace.delete", "workspace/delete"):
                res = await self.workspace_handler.delete_workspace(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("workspace.insertBefore", "workspace/insertBefore"):
                res = await self.workspace_handler.insert_before(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("workspace.insertSessionBefore", "workspace/insertSessionBefore"):
                res = await self.workspace_handler.insert_session_before(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("workspace.archiveSession", "workspace/archiveSession"):
                res = await self.workspace_handler.archive_session(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("workspace/files", "workspace.files"):
                res = await self.workspace_handler.list_files(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("session.list", "session/list", "sessions/list"):
                res = await self.sessions_handler.list_sessions(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("jobs.list", "jobs/list"):
                res = await self.jobs_handler.list_jobs({**req_payload, "sessionId": req_payload.get("sessionId") or parsed_query.get("sessionId", ["default-session"])[0]})
                await send_rpc_success(res)
                return

            if rpc_method in ("session.create", "session/create"):
                res = await self.sessions_handler.create_session(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("session.history", "session/history"):
                res = await self.sessions_handler.get_history({**req_payload, "sessionId": req_payload.get("sessionId") or parsed_query.get("sessionId", ["default-session"])[0]})
                await send_rpc_success(res)
                return

            if rpc_method in ("session.rename", "session/rename"):
                res = await self.sessions_handler.rename_session(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("session.fork", "session/fork"):
                res = await self.sessions_handler.fork_session(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("session.prompt", "session/prompt"):
                res = await self.sessions_handler.prompt_session(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("session.attachment", "session/attachment"):
                res = await self.sessions_handler.add_attachment(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("session.updateQueue", "session/updateQueue"):
                res = await self.sessions_handler.update_queue(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("session.cancel", "session/cancel"):
                res = await self.sessions_handler.cancel_session(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("session.models", "session/models", "models/discover", "llm.models"):
                res = await self.sessions_handler.get_models(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("model/set", "model.set", "session.selectModel", "session/selectModel"):
                res = await self.sessions_handler.select_model(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("plan/set", "plan.set"):
                active = bool(req_payload.get("active", False))
                plan_mode = self.ctx.get("plan_mode")
                if plan_mode:
                    plan_mode.set_active(active)
                await send_rpc_success({"success": True, "planMode": active})
                return

            if rpc_method in ("goal/action", "goal.action"):
                action = req_payload.get("action")
                if action == "create":
                    res = await self.goals_handler.create_goal(req_payload)
                elif action == "pause":
                    res = await self.goals_handler.pause_goal(req_payload)
                elif action == "resume":
                    res = await self.goals_handler.resume_goal(req_payload)
                elif action == "complete":
                    res = await self.goals_handler.complete_goal(req_payload)
                else:
                    res = await self.goals_handler.edit_goal(req_payload)
                await send_rpc_success({"success": True, "goal": res.get("goal")})
                return

            if rpc_method.startswith("goal.") or rpc_method.startswith("goal/"):
                action = rpc_method.split(".", 1)[-1].split("/", 1)[-1]
                if action == "create":
                    res = await self.goals_handler.create_goal(req_payload)
                elif action == "pause":
                    res = await self.goals_handler.pause_goal(req_payload)
                elif action == "resume":
                    res = await self.goals_handler.resume_goal(req_payload)
                elif action == "complete":
                    res = await self.goals_handler.complete_goal(req_payload)
                elif action == "clear":
                    res = await self.goals_handler.clear_goal(req_payload)
                else:
                    res = await self.goals_handler.edit_goal(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("settings.describe", "settings/describe"):
                res = await self.settings_handler.describe_settings(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("settings.openDocument", "settings/openDocument"):
                res = await self.settings_handler.open_document(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("settings.update", "settings/update", "settings/save"):
                res = await self.settings_handler.update_settings(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("settings.replace", "settings/replace"):
                res = await self.settings_handler.replace_settings(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("settings.mutate", "settings/mutate"):
                res = await self.settings_handler.mutate_settings(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("permission/set", "permission.set"):
                preset = req_payload.get("preset", "workspace-write")
                await send_rpc_success({"success": True, "preset": preset})
                return

            if rpc_method in ("agentPreset.list", "agentPreset/list", "presets/list"):
                res = await self.agent_presets_handler.list_presets(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("agentPreset.select", "agentPreset/select"):
                res = await self.agent_presets_handler.select_preset(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("agentPreset.read", "agentPreset/read"):
                res = await self.agent_presets_handler.read_preset(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("agentPreset.copy", "agentPreset/copy"):
                res = await self.agent_presets_handler.copy_preset(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("agentPreset.openDocument", "agentPreset/openDocument"):
                res = await self.agent_presets_handler.open_document(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("agentPreset.remove", "agentPreset/remove"):
                res = await self.agent_presets_handler.remove_preset(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("subagent.list", "subagent/list"):
                res = await self.subagents_handler.list_subagents(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("subagent.history", "subagent/history"):
                res = await self.subagents_handler.get_history({**req_payload, "subagentId": req_payload.get("subagentId") or parsed_query.get("subagentId", [None])[0]})
                await send_rpc_success(res)
                return

            if rpc_method in ("subagent.prompt", "subagent/prompt"):
                res = await self.subagents_handler.prompt_subagent(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("subagent.interrupt", "subagent/interrupt"):
                res = await self.subagents_handler.interrupt_subagent(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("credentials.describe", "credentials/describe"):
                res = await self.credentials_handler.describe_credentials(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("credentials.set", "credentials/set"):
                res = await self.credentials_handler.set_credentials(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("credentials.unset", "credentials/unset"):
                res = await self.credentials_handler.unset_credentials(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("skill.list", "skill/list"):
                res = await self.skills_handler.list_skills(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("llm.providers", "llm/providers"):
                res = await self.llm_handler.list_providers(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("llm.discoverModels", "llm/discoverModels"):
                res = await self.llm_handler.discover_models(req_payload)
                await send_rpc_success(res)
                return

            if rpc_method in ("session.search", "session/search"):
                res = await self.session_search_handler.search_sessions(req_payload)
                await send_rpc_success(res)
                return

        except ValueError as ve:
            await send_rpc_error("bad-request", str(ve))
            return
        except Exception as e:
            await send_rpc_error("internal", str(e))
            return

        await send_rpc_error("not-found", f"Unknown method or endpoint: {path}")

    async def _handle_mux_stream(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        response.write_status(200)
        response.write_header("Content-Type", "text/event-stream")
        response.write_header("Cache-Control", "no-cache")
        response.write_header("Connection", "keep-alive")
        response.write_header("Access-Control-Allow-Origin", "*")
        await response.send_headers()

        await response.write_chunk(b": connected\n\n")

        queue = asyncio.Queue()
        self._mux_clients.append(queue)
        try:
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

        await response.write_chunk(b": connected\n\n")

        queue = asyncio.Queue()
        self._host_clients.append(queue)
        try:
            order_frame = {
                "type": "host/workspace-order-changed",
                "workspaceIds": list(self._workspace_order),
            }
            await response.write_chunk(format_sse_frame(order_frame))

            for ws_view in self._workspaces.values():
                ws_frame = {
                    "type": "host/workspace-changed",
                    "workspace": ws_view,
                }
                await response.write_chunk(format_sse_frame(ws_frame))

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
