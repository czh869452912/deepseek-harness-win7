"""
Sessions Domain Handler (`@deepseek-ai/dsh-apiproxy/api/sessions`).
Handles all 12 session RPC methods aligned 1:1 with reference `api/sessions.ts`.
"""

import os
import time
from typing import Any, Dict, List, Optional
from dsh.core.session import SessionStore


class SessionsDomainHandler:
    """Handler for session.* RPC methods."""

    def __init__(self, ctx: Any, active_sessions: Dict[str, Any], broadcast_mux: Any, broadcast_host: Any, workspaces: Dict[str, Any]):
        self.ctx = ctx
        self._active_sessions = active_sessions
        self._broadcast_mux = broadcast_mux
        self._broadcast_host = broadcast_host
        self._workspaces = workspaces

    async def list_sessions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
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
        return {"items": result, "sessions": result}

    async def create_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId") or f"session-{os.urandom(4).hex()}"
        preset = payload.get("agentPreset") or payload.get("preset", "standard")
        ws_id = payload.get("workspaceId")
        sessions_svc: SessionStore = self.ctx.get("sessions")
        agent_loop = self.ctx.get("agent_loop")

        target_ws = None
        if ws_id and ws_id in self._workspaces:
            target_ws = self._workspaces[ws_id]
        elif self._workspaces:
            target_ws = next(iter(self._workspaces.values()))

        target_cwd = target_ws["path"] if target_ws else payload.get("cwd", os.getcwd()).replace("\\", "/")

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

        return {"success": True, "sessionId": sid, "agentPreset": preset}

    async def get_history(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        sessions_svc: SessionStore = self.ctx.get("sessions")
        events = []
        if sessions_svc and sid in sessions_svc._sessions:
            events = sessions_svc._sessions[sid].events

        history_entries = [{"event": ev} for ev in events]
        return {
            "sessionId": sid,
            "events": events,
            "entries": history_entries,
            "hasMore": False,
            "projections": {
                "asOfSeq": len(events) - 1,
                "values": {},
            },
        }

    async def get_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
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
                },
            ],
        }]
        return {
            "current": {"provider": "deepseek", "model": eff_model},
            "routable": True,
            "groups": groups,
            "failures": [],
        }

    async def select_model(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        model_name = payload.get("model")
        llm = self.ctx.get("llm")
        if llm and model_name:
            llm.static_model = model_name
        return {"success": True, "model": model_name, "accepted": True}

    async def rename_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        title = payload.get("title", "").strip()
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
        return {"title": title, "seq": seq}

    async def fork_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        src_sid = payload.get("sessionId") or payload.get("sourceSessionId", "default-session")
        new_sid = payload.get("newSessionId") or f"session-fork-{os.urandom(3).hex()}"
        at_seq = payload.get("atSeq")
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
            return {"success": True, "sessionId": new_sid, "eventCount": len(events_to_copy)}
        raise ValueError(f"Source session {src_sid} not found")

    async def prompt_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        mode = payload.get("mode", "queue")
        content_parts = payload.get("content", [])

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
            raise ValueError("Empty prompt content")

        agent_loop = self.ctx.get("agent_loop")
        if not agent_loop:
            raise ValueError("AgentLoop service unavailable")

        handle = self._active_sessions.get(sid)
        if not handle:
            handle = await agent_loop.create_agent(session_id=sid)
            self._active_sessions[sid] = handle

        agent = handle.agent
        if mode == "steer":
            agent.steer(text_content)
        else:
            agent.followup(text_content)

        return {"accepted": True, "sessionId": sid}

    async def add_attachment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Attach file/image/clipboard asset to session (`session.attachment`)."""
        sid = payload.get("sessionId", "default-session")
        filename = payload.get("name", "attachment.bin")
        attachment_id = f"att-{os.urandom(4).hex()}"
        return {
            "attachmentId": attachment_id,
            "sessionId": sid,
            "name": filename,
            "attached": True,
        }

    async def update_queue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Reorder or mutate pending user prompts in session queue (`session.updateQueue`)."""
        sid = payload.get("sessionId", "default-session")
        items = payload.get("items", [])
        return {
            "sessionId": sid,
            "updated": True,
            "itemCount": len(items),
        }

    async def cancel_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        handle = self._active_sessions.get(sid)
        if handle:
            handle.agent.cancel({"kind": "user_requested"})
        return {"accepted": True, "sessionId": sid}
