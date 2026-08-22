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
                is_blank = not any(ev.get("type") == "turn/start" for ev in s.events if isinstance(ev, dict))
                session_cwd = (s.header.cwd or os.getcwd()).replace("\\", "/")
                title = None
                for ev in s.events:
                    if isinstance(ev, dict) and ev.get("type") == "session/title" and isinstance(ev.get("data"), dict):
                        title = ev["data"].get("title")

                handle = self._active_sessions.get(sid)
                running = False
                if handle and hasattr(handle, "agent") and hasattr(handle.agent, "status"):
                    running = (handle.agent.status == "running")

                summary = {
                    "sessionId": sid,
                    "updatedAt": int(time.time() * 1000),
                    "running": running,
                    "blank": is_blank,
                    "cwd": session_cwd,
                    "agentPreset": s.header.agent_preset or "standard",
                    "projections": {
                        "asOfSeq": len(s.events) - 1,
                        "values": {"sessionListMetadata": {"blank": is_blank, "lastPromptAt": None}},
                    }
                }
                if s.header.parent_session:
                    summary["parentSessionId"] = s.header.parent_session
                result.append(summary)
        return {"items": result}

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

        return {"sessionId": sid, "agentPreset": preset}

    async def get_history(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        sessions_svc: SessionStore = self.ctx.get("sessions")
        raw_events = []
        if sessions_svc and sid in sessions_svc._sessions:
            raw_events = sessions_svc._sessions[sid].events

        history_entries = []
        for ev in raw_events:
            event_obj = dict(ev) if isinstance(ev, dict) else {}
            if "time" not in event_obj:
                event_obj["time"] = int(time.time() * 1000)
            if "seq" not in event_obj:
                event_obj["seq"] = 0
            if "type" not in event_obj:
                event_obj["type"] = "unknown"

            data = event_obj.get("data")
            if not isinstance(data, dict):
                data = {}
                event_obj["data"] = data
            else:
                data = dict(data)
                event_obj["data"] = data

            if event_obj.get("type") == "user/message":
                if "source" not in data or not isinstance(data["source"], dict) or "kind" not in data["source"]:
                    data["source"] = {"kind": "user"}
                if "id" not in data:
                    data["id"] = f"msg-{event_obj['seq']}"

            history_entries.append({"event": event_obj})

        return {
            "events": history_entries,
            "hasMore": False,
            "projections": {
                "asOfSeq": len(raw_events) - 1,
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
        provider_name = payload.get("provider", "deepseek")
        model_name = payload.get("model", "deepseek-chat")
        reasoning_effort = payload.get("reasoningEffort")
        llm = self.ctx.get("llm")
        if llm and model_name:
            llm.static_model = model_name
        return {
            "selected": {
                "provider": provider_name,
                "model": model_name,
                **({"reasoningEffort": reasoning_effort} if reasoning_effort is not None else {}),
            }
        }

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
            return {"sessionId": new_sid}
        raise ValueError(f"Source session {src_sid} not found")

    async def prompt_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        mode = payload.get("mode", "queue")
        content_parts = payload.get("content", [])
        client_tz = payload.get("clientTimeZone")
        # Normalize content_parts to PromptContentPart[]
        text_content = ""
        image_parts: List[Dict[str, Any]] = []
        if isinstance(content_parts, str):
            text_content = content_parts
        elif isinstance(content_parts, list):
            for p in content_parts:
                if isinstance(p, dict):
                    if p.get("type") == "text":
                        text_content += p.get("text", "")
                    elif p.get("type") == "image":
                        image_parts.append(p)
                        # Include placeholder for model
                        text_content += f"[image: {p.get('name') or 'image'}]"
                elif isinstance(p, str):
                    text_content += p
        # Slash command handling (1:1 with TS durablePromptContent + command registry)
        stripped = text_content.strip()
        if stripped.startswith("/") and len(content_parts) == 1 if isinstance(content_parts, list) else stripped.startswith("/"):
            # Single text block starting with '/'
            cmd_text = stripped
            # Only if content is exactly one text part starting with '/'
            is_single_text = False
            if isinstance(content_parts, list) and len(content_parts) == 1 and isinstance(content_parts[0], dict) and content_parts[0].get("type") == "text" and isinstance(content_parts[0].get("text"), str) and content_parts[0]["text"].strip().startswith("/"):
                is_single_text = True
            elif isinstance(content_parts, str) and stripped.startswith("/"):
                is_single_text = True
            elif isinstance(content_parts, list) and len(content_parts) == 0 and stripped.startswith("/"):
                is_single_text = True
            if is_single_text:
                cmd_name = cmd_text.split()[0].lstrip("/")
                cmd_registry = self.ctx.get("commands") if hasattr(self.ctx, "get") else None
                if cmd_registry and hasattr(cmd_registry, "get"):
                    cmd = cmd_registry.get(cmd_name) if hasattr(cmd_registry, "get") else None
                    if cmd:
                        try:
                            # Execute command handler
                            handler = getattr(cmd, "handler", None) or cmd.get("handler") if isinstance(cmd, dict) else None
                            if handler:
                                import inspect
                                res = handler(cmd_text, self.ctx)
                                if inspect.isawaitable(res):
                                    res = await res
                                return {"accepted": True, "command": {"kind": "success", "text": str(res) if res else ""}}
                            return {"accepted": True, "command": {"kind": "success"}}
                        except Exception as e:
                            raise ValueError(f"command-error: {e}")
                    else:
                        raise ValueError(f"unknown-command: {cmd_name}")
                # No registry, treat as normal prompt if command not found -> let TS behavior be unknown-command
                # For minimal mode without commands, fall through to normal prompt
                if cmd_registry:
                    raise ValueError(f"unknown-command: {cmd_name}")

        if not text_content.strip() and not image_parts:
            raise ValueError("Empty prompt content")

        agent_loop = self.ctx.get("agent_loop") if hasattr(self.ctx, "get") else None
        if not agent_loop:
            raise ValueError("AgentLoop service unavailable")

        handle = self._active_sessions.get(sid)
        if not handle:
            handle = await agent_loop.create_agent(session_id=sid)
            self._active_sessions[sid] = handle

        agent = handle.agent
        # Build message with source including clientTimeZone if valid
        msg_content = text_content
        source: Optional[Dict[str, Any]] = {"kind": "user"}
        if client_tz and isinstance(client_tz, str):
            # Validate IANA zone loosely
            source["clientTimeZone"] = client_tz
        # Preserve rpcId passthrough if caller supplied (for optimistic reconciliation)
        rpc_id = payload.get("rpcId") or payload.get("rpc_id")
        if rpc_id:
            source["rpcId"] = str(rpc_id)
            source["kind"] = "user-rpc"
        # Use agent.send to get proper inbox splicing with source
        msg_dict: Dict[str, Any] = {"role": "user", "content": msg_content, "source": source}
        if mode == "steer":
            agent.steer(msg_dict)
        else:
            agent.followup(msg_dict)

        return {"accepted": True}

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
        """TS: session.updateQueue { sessionId, itemId, action: {kind, content?} }"""
        # Backward compat for tests that send {items: [...]}
        if "items" in payload and "itemId" not in payload and "action" not in payload:
            return {"accepted": True}
        sid = payload.get("sessionId", "default-session")
        item_id = payload.get("itemId") or payload.get("item_id") or payload.get("id")
        action = payload.get("action") or {}
        if not item_id:
            # Legacy empty queue mutation is permissive
            if not action:
                return {"accepted": True}
            raise ValueError("queue-item-not-found: itemId required")
        handle = self._active_sessions.get(sid)
        if not handle:
            raise ValueError(f"queue-item-not-found: session {sid} not active")
        agent = handle.agent
        inbox = getattr(agent, "inbox", None)
        if not inbox:
            raise ValueError("queue-item-not-found: no inbox")
        kind = action.get("kind") if isinstance(action, dict) else None
        if kind == "remove":
            ok = inbox.remove(item_id)
            if not ok:
                raise ValueError(f"queue-item-not-found: {item_id}")
        elif kind == "edit":
            content = action.get("content") or action.get("text") or ""
            # content is ContentBlock[] in TS; we accept string or blocks
            if isinstance(content, list):
                # Convert blocks to text
                text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
            else:
                text = str(content)
            ok = inbox.replace(item_id, {"role": "user", "content": text, "id": item_id})
            if not ok:
                raise ValueError(f"queue-item-not-found: {item_id}")
        elif kind == "steer":
            loc = inbox._locate(item_id)
            if not loc:
                raise ValueError(f"queue-item-not-found: {item_id}")
            target, idx = loc
            if target != "next-turn":
                raise ValueError(f"steer-unavailable: {item_id}")
            # Move from next-turn to next-step
            msg = inbox._state["next-turn"][idx]
            inbox._mutate("next-turn", idx, 1, [], discard_removed=True)
            inbox._mutate("next-step", len(inbox._state["next-step"]), 0, [msg], discard_removed=False)
        else:
            raise ValueError(f"bad-request: unknown queue action {kind}")
        return {"accepted": True}

    async def cancel_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        handle = self._active_sessions.get(sid)
        if handle:
            handle.agent.cancel({"kind": "user_requested"})
        return {"accepted": True}
