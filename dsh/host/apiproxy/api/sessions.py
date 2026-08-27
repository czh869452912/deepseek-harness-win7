"""
Sessions Domain Handler (`@deepseek-ai/dsh-apiproxy/api/sessions`).
1:1 with reference `api/sessions.ts`.
"""

import os
import time
from typing import Any, Dict, List, Optional
from dsh.core.session import SessionStore


def _is_blank(events):
    return not any(isinstance(ev, dict) and ev.get("type") == "turn/start" for ev in events)

def _last_prompt_at(events):
    last = None
    for ev in events:
        if isinstance(ev, dict) and ev.get("type") == "user/message":
            t = ev.get("time")
            if isinstance(t, int):
                if last is None or t > last:
                    last = t
            else:
                # fallback to data time if present
                d = ev.get("data", {})
                if isinstance(d, dict):
                    # ignore
                    pass
    return last


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
                is_blank = _is_blank(s.events)
                last_prompt = _last_prompt_at(s.events)
                created_at = getattr(s.header, "created_at", int(time.time()*1000))
                updated_at = max(created_at, last_prompt) if last_prompt is not None else created_at
                # handle header.cwd fallback
                session_cwd = (s.header.cwd or os.getcwd()).replace("\\", "/")
                # title via projection or last title event
                title = None
                for ev in s.events:
                    if isinstance(ev, dict) and ev.get("type") == "session/title" and isinstance(ev.get("data"), dict):
                        title = ev["data"].get("title")
                handle = self._active_sessions.get(sid)
                running = False
                if handle and hasattr(handle, "agent") and hasattr(handle.agent, "status"):
                    try:
                        running = (handle.agent.status == "running")
                    except Exception:
                        running = False
                summary = {
                    "sessionId": sid,
                    "updatedAt": int(updated_at),
                    "running": running,
                    "blank": is_blank,
                    "cwd": session_cwd,
                    "agentPreset": s.header.agent_preset or "standard",
                    "projections": {
                        "asOfSeq": len(s.events) - 1,
                        "values": {"sessionListMetadata": {"blank": is_blank, "lastPromptAt": last_prompt}},
                    }
                }
                if s.header.parent_session:
                    summary["parentSessionId"] = s.header.parent_session
                if getattr(s.header, "origin", None):
                    summary["origin"] = s.header.origin
                result.append(summary)
            # sort descending by updatedAt (1:1 with TS)
            result.sort(key=lambda x: x["updatedAt"], reverse=True)
        return {"items": result}

    async def create_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId") or f"session-{os.urandom(4).hex()}"
        preset = payload.get("agentPreset") or payload.get("preset", "standard")
        ws_id = payload.get("workspaceId")
        cwd_req = payload.get("cwd")
        sessions_svc: SessionStore = self.ctx.get("sessions")
        agent_loop = self.ctx.get("agent_loop")
        # 1:1 conflict check: sessionId with different cwd fails
        if sessions_svc and sid in sessions_svc._sessions:
            existing = sessions_svc._sessions[sid]
            existing_cwd = (existing.header.cwd or "").replace("\\", "/")
            new_cwd_norm = (cwd_req or existing_cwd or os.getcwd()).replace("\\", "/") if cwd_req else existing_cwd
            if cwd_req and existing_cwd and existing_cwd != new_cwd_norm:
                raise ValueError("session-conflict: session '{}' exists with different cwd".format(sid))
            # idempotent return
            return {"sessionId": sid, "agentPreset": existing.header.agent_preset or preset}
        target_ws = None
        if ws_id and ws_id in self._workspaces:
            target_ws = self._workspaces[ws_id]
        elif self._workspaces:
            target_ws = next(iter(self._workspaces.values()))
        target_cwd = None
        if cwd_req:
            target_cwd = cwd_req.replace("\\", "/")
        elif target_ws:
            target_cwd = target_ws["path"]
        else:
            target_cwd = os.getcwd().replace("\\", "/")
        # validate preset exists (1:1)
        if self.ctx and hasattr(self.ctx, "get") and preset:
            from dsh.host.apiproxy.api.agent_presets import AgentPresetsDomainHandler
            tmp = AgentPresetsDomainHandler(self.ctx)
            try:
                svc = tmp._get_service()
                preset_list = await svc.list()
                preset_ids = [p.id for p in preset_list]
                if preset_ids and preset not in preset_ids:
                    raise ValueError("agent-preset-not-found: unknown preset '{}'".format(preset))
            except ValueError:
                raise
            except Exception:
                pass
        if sessions_svc:
            try:
                s = sessions_svc.create(sid)
            except ValueError:
                # already exists -> idempotent
                s = sessions_svc._sessions[sid]
            s.header.cwd = target_cwd
            s.header.agent_preset = preset
        if agent_loop and sid not in self._active_sessions:
            try:
                handle = await agent_loop.create_agent(session_id=sid)
                self._active_sessions[sid] = handle
            except Exception:
                pass
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
        before_seq = payload.get("beforeSeq")
        max_messages = payload.get("maxMessages")
        sessions_svc: SessionStore = self.ctx.get("sessions")
        raw_events = []
        if sessions_svc and sid in sessions_svc._sessions:
            raw_events = sessions_svc._sessions[sid].events
        # message boundary pagination (simplified 1:1): paginate by user/message + assistant/message
        # For Python, we treat each user/message as a message boundary; include following tool/result until next user/message
        # Apply beforeSeq and maxMessages
        filtered = raw_events
        if before_seq is not None:
            try:
                b = int(before_seq)
                filtered = [ev for ev in raw_events if ev.get("seq", 0) < b]
            except Exception:
                pass
        # Determine message count
        def count_messages(events):
            return sum(1 for ev in events if ev.get("type") in ("user/message", "assistant/message"))
        has_more = False
        if max_messages is not None:
            try:
                mm = int(max_messages)
                if mm > 0 and count_messages(filtered) > mm:
                    # find cut point aligning to message boundary
                    # collect seqs of message starts
                    msg_indices = [i for i, ev in enumerate(filtered) if ev.get("type") in ("user/message", "assistant/message")]
                    if len(msg_indices) > mm:
                        cut_idx = msg_indices[len(msg_indices) - mm]
                        # include from cut_idx to end? Actually history returns latest window, so slice from cut_idx
                        # For simplicity, return last mm messages window
                        start_ev_idx = cut_idx
                        has_more = True
                        filtered = filtered[start_ev_idx:]
                        # recount to ensure hasMore accurate
                        # if there are earlier messages beyond window, hasMore True
                    else:
                        has_more = False
                else:
                    has_more = False
            except Exception:
                pass
        history_entries = []
        for ev in filtered:
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
                    data["id"] = "msg-{}".format(event_obj['seq'])
            # view: minimal tool view for tool/result events (1:1 would be presenter)
            view = None
            if event_obj.get("type") == "tool/result" and isinstance(data, dict):
                view = {"kind": "tool", "name": data.get("name", ""), "result": data.get("result", "")[:500]}
            entry = {"event": event_obj}
            if view:
                entry["view"] = view
            history_entries.append(entry)
        return {
            "events": history_entries,
            "hasMore": has_more,
            "projections": {
                "asOfSeq": len(raw_events) - 1,
                "values": {},
            },
        }

    async def get_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from dsh.host.apiproxy.api.llm import build_model_catalog
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        sid = payload.get("sessionId", "default-session")

        current_provider = "deepseek"
        current_model = "deepseek-chat"
        reasoning = None

        # Host-wide default selection is the same baseline used by the TS
        # session.models endpoint when no live agent has overridden it.
        default_selection = self.ctx.get("agentDefaultModel") if hasattr(self.ctx, "get") else None
        if default_selection is not None:
            try:
                selected = default_selection.current_selection()
                if isinstance(selected, dict):
                    current_provider = selected.get("provider", current_provider)
                    current_model = selected.get("model", current_model)
                    reasoning = selected.get("reasoningEffort")
            except Exception:
                pass

        if llm and hasattr(llm, "resolve_model"):
            try:
                current_model = llm.resolve_model()
            except Exception:
                pass

        handle = self._active_sessions.get(sid)
        if handle and hasattr(handle, "agent"):
            sel = getattr(handle.agent, "_model_selection", None)
            if isinstance(sel, dict) and sel.get("provider"):
                current_provider = sel["provider"]
                current_model = sel.get("model", current_model)
                reasoning = sel.get("reasoningEffort")

        catalog = await build_model_catalog(self.ctx)
        groups = catalog.get("groups", [])
        failures = catalog.get("failures", [])

        # routable: whether adapter serves current provider
        routable = True
        if llm and hasattr(llm, "_adapters"):
            routable = current_provider in llm._adapters
        elif llm and hasattr(llm, "list_providers"):
            try:
                provs = [p["id"] for p in llm.list_providers() if isinstance(p, dict)]
                routable = current_provider in provs
            except Exception:
                routable = True

        current = {"provider": current_provider, "model": current_model}
        if reasoning is not None:
            current["reasoningEffort"] = reasoning

        return {
            "current": current,
            "routable": routable,
            "groups": groups,
            "failures": failures,
        }

    async def select_model(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider_name = payload.get("provider", "deepseek")
        model_name = payload.get("model", "deepseek-chat")
        reasoning_effort = payload.get("reasoningEffort")
        sid = payload.get("sessionId", "default-session")
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None

        if llm and hasattr(llm, "resolve_model_info"):
            try:
                info = llm.resolve_model_info(provider_name, model_name)
                import inspect
                if inspect.isawaitable(info):
                    info = await info
            except Exception as e:
                raise ValueError("model-unavailable: {}".format(e))

        sel_dict = {
            "provider": provider_name,
            "model": model_name,
            **({"reasoningEffort": reasoning_effort} if reasoning_effort is not None else {})
        }

        handle = self._active_sessions.get(sid)
        if handle and hasattr(handle, "agent"):
            handle.agent._model_selection = sel_dict
            if hasattr(handle.agent, "options") and handle.agent.options:
                handle.agent.options.provider = provider_name
                handle.agent.options.model = model_name
        if llm:
            if hasattr(llm, "static_model"):
                llm.static_model = model_name

        default_selection = self.ctx.get("agentDefaultModel") if hasattr(self.ctx, "get") else None
        if default_selection is not None and hasattr(default_selection, "save_selection"):
            try:
                saved = default_selection.save_selection(sel_dict)
                import inspect
                if inspect.isawaitable(saved):
                    await saved
            except Exception:
                # Selection remains valid for the active agent even when the
                # optional settings backend is unavailable.
                pass

        return {"selected": sel_dict}

    async def rename_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        title = payload.get("title", "")
        if not isinstance(title, str):
            raise ValueError("title-invalid: title must be string")
        norm = title.strip()
        if not norm:
            raise ValueError("title-invalid: title must be non-empty")
        if len(norm) > 200:
            norm = norm[:200]
        sessions_svc: SessionStore = self.ctx.get("sessions")
        seq = int(time.time())
        if sessions_svc and sid in sessions_svc._sessions:
            s = sessions_svc._sessions[sid]
            s.append({
                "type": "session/title",
                "data": {"title": norm, "source": "user"},
                "seq": len(s.events),
            })
            seq = len(s.events) - 1
        await self._broadcast_mux({
            "type": "session/projection",
            "sessionId": sid,
            "key": "title",
            "value": norm,
            "seq": seq,
        })
        return {"title": norm, "seq": seq}

    async def fork_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        src_sid = payload.get("sessionId") or payload.get("sourceSessionId", "default-session")
        new_sid = payload.get("newSessionId") or "session-fork-{}".format(os.urandom(3).hex())
        at_seq = payload.get("atSeq")
        sessions_svc: SessionStore = self.ctx.get("sessions")
        agent_loop = self.ctx.get("agent_loop")
        if not sessions_svc or src_sid not in sessions_svc._sessions:
            raise ValueError("session-not-found: source session {} not found".format(src_sid))
        src_session = sessions_svc._sessions[src_sid]
        # find turn/end boundary at or after at_seq (1:1)
        cut_idx = len(src_session.events)
        if at_seq is not None:
            try:
                at = int(at_seq)
                # find first turn/end at or after at
                found = None
                for i, ev in enumerate(src_session.events):
                    if ev.get("type") == "turn/end" and ev.get("seq", i) >= at:
                        found = i + 1
                        break
                if found is None:
                    # check if at is beyond log -> use last completed turn
                    # find last turn/end
                    last_turn_end = None
                    for i, ev in enumerate(src_session.events):
                        if ev.get("type") == "turn/end":
                            last_turn_end = i + 1
                    if last_turn_end is not None:
                        cut_idx = last_turn_end
                    else:
                        cut_idx = len(src_session.events)
                    if at is not None and found is None and any(ev.get("type") == "turn/start" and ev.get("seq", 0) >= at for ev in src_session.events):
                        # at points inside open turn -> fork-unavailable
                        raise ValueError("fork-unavailable: anchor is inside an open turn")
                else:
                    cut_idx = found
            except ValueError as ve:
                if "fork-unavailable" in str(ve):
                    raise
                cut_idx = len(src_session.events)
        else:
            # default to last completed turn
            last_turn_end = None
            for i, ev in enumerate(src_session.events):
                if ev.get("type") == "turn/end":
                    last_turn_end = i + 1
            if last_turn_end is not None:
                cut_idx = last_turn_end
        new_session = sessions_svc.create(new_sid)
        new_session.header.parent_session = src_sid
        new_session.header.agent_preset = src_session.header.agent_preset
        new_session.header.cwd = src_session.header.cwd
        events_to_copy = src_session.events[:cut_idx]
        for ev in events_to_copy:
            new_session.append(ev.get("type", "unknown"), ev.get("data", {}))
        # seed title from source
        if agent_loop:
            try:
                handle = await agent_loop.create_agent(session_id=new_sid)
                self._active_sessions[new_sid] = handle
            except Exception:
                pass
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

    async def prompt_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        mode = payload.get("mode", "queue")
        content_parts = payload.get("content", [])
        client_tz = payload.get("clientTimeZone")
        # normalize content_parts to PromptContentPart[]
        text_content = ""
        image_parts = []
        if isinstance(content_parts, str):
            text_content = content_parts
        elif isinstance(content_parts, list):
            for p in content_parts:
                if isinstance(p, dict):
                    if p.get("type") == "text":
                        text_content += p.get("text", "")
                    elif p.get("type") == "image":
                        image_parts.append(p)
                        text_content += "[image: {}]".format(p.get('name') or 'image')
                elif isinstance(p, str):
                    text_content += p
        stripped = text_content.strip()
        # 1:1 slash command: only if exactly one text block starting with /
        is_single_text = False
        if isinstance(content_parts, list) and len(content_parts) == 1 and isinstance(content_parts[0], dict) and content_parts[0].get("type") == "text" and isinstance(content_parts[0].get("text"), str) and content_parts[0]["text"].strip().startswith("/"):
            is_single_text = True
        elif isinstance(content_parts, str) and stripped.startswith("/"):
            is_single_text = True
        if is_single_text and stripped.startswith("/"):
            cmd_name = stripped.split()[0].lstrip("/")
            cmd_registry = self.ctx.get("commands") if hasattr(self.ctx, "get") else None
            if cmd_registry:
                cmd = None
                try:
                    if hasattr(cmd_registry, "get"):
                        cmd = cmd_registry.get(cmd_name)
                except Exception:
                    cmd = None
                if cmd:
                    try:
                        handler = getattr(cmd, "handler", None) or (cmd.get("handler") if isinstance(cmd, dict) else None)
                        if handler:
                            import inspect
                            res = handler(stripped, self.ctx)
                            if inspect.isawaitable(res):
                                res = await res
                            return {"accepted": True, "command": {"kind": "success", "text": str(res) if res else ""}}
                        return {"accepted": True, "command": {"kind": "success"}}
                    except Exception as e:
                        raise ValueError("command-error: {}".format(e))
                raise ValueError("unknown-command: {}".format(cmd_name))
        if not text_content.strip() and not image_parts:
            raise ValueError("Empty prompt content")
        # IANA timezone validation (minimal)
        if client_tz and isinstance(client_tz, str):
            # basic check: contains "/" or known values; failuresRaise invalid-time-zone
            if "/" not in client_tz and client_tz not in ("UTC", "GMT"):
                # try validate via zoneinfo if available
                try:
                    import zoneinfo
                    zoneinfo.ZoneInfo(client_tz)
                except Exception:
                    raise ValueError("invalid-time-zone: {}".format(client_tz))
        agent_loop = self.ctx.get("agent_loop") if hasattr(self.ctx, "get") else None
        if not agent_loop:
            raise ValueError("AgentLoop service unavailable")
        handle = self._active_sessions.get(sid)
        if not handle:
            handle = await agent_loop.create_agent(session_id=sid)
            self._active_sessions[sid] = handle
        agent = handle.agent
        msg_content = text_content
        source = {"kind": "user"}
        if client_tz and isinstance(client_tz, str):
            source["clientTimeZone"] = client_tz
        rpc_id = payload.get("rpcId") or payload.get("rpc_id")
        if rpc_id:
            source["rpcId"] = str(rpc_id)
            source["kind"] = "user-rpc"
        msg_dict = {"role": "user", "content": msg_content, "source": source}
        if image_parts:
            msg_dict["_image_parts"] = image_parts
        if mode == "steer":
            agent.steer(msg_dict)
        else:
            agent.followup(msg_dict)
        return {"accepted": True}

    async def add_attachment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        filename = payload.get("name", "attachment.bin")
        attachment_id = "att-{}".format(os.urandom(4).hex())
        return {
            "attachmentId": attachment_id,
            "sessionId": sid,
            "name": filename,
            "attached": True,
        }

    async def update_queue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if "items" in payload and "itemId" not in payload and "action" not in payload:
            return {"accepted": True}
        sid = payload.get("sessionId", "default-session")
        item_id = payload.get("itemId") or payload.get("item_id") or payload.get("id")
        action = payload.get("action") or {}
        if not item_id:
            if not action:
                return {"accepted": True}
            raise ValueError("queue-item-not-found: itemId required")
        handle = self._active_sessions.get(sid)
        if not handle:
            raise ValueError("queue-item-not-found: session {} not active".format(sid))
        agent = handle.agent
        inbox = getattr(agent, "inbox", None)
        if not inbox:
            raise ValueError("queue-item-not-found: no inbox")
        kind = action.get("kind") if isinstance(action, dict) else None
        if kind == "remove":
            ok = inbox.remove(item_id) if hasattr(inbox, "remove") else False
            if not ok:
                raise ValueError("queue-item-not-found: {}".format(item_id))
        elif kind == "edit":
            content = action.get("content") or action.get("text") or ""
            if isinstance(content, list):
                text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
            else:
                text = str(content)
            ok = inbox.replace(item_id, {"role": "user", "content": text, "id": item_id}) if hasattr(inbox, "replace") else False
            if not ok:
                raise ValueError("queue-item-not-found: {}".format(item_id))
        elif kind == "steer":
            loc = inbox._locate(item_id) if hasattr(inbox, "_locate") else None
            if not loc:
                raise ValueError("queue-item-not-found: {}".format(item_id))
            target, idx = loc
            if target != "next-turn":
                raise ValueError("steer-unavailable: {}".format(item_id))
            msg = inbox._state["next-turn"][idx]
            inbox._mutate("next-turn", idx, 1, [], discard_removed=True)
            inbox._mutate("next-step", len(inbox._state["next-step"]), 0, [msg], discard_removed=False)
        else:
            raise ValueError("bad-request: unknown queue action {}".format(kind))
        return {"accepted": True}

    async def cancel_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        handle = self._active_sessions.get(sid)
        if handle:
            try:
                handle.agent.cancel({"kind": "user_requested"})
            except Exception:
                pass
        return {"accepted": True}
