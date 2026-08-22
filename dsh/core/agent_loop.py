"""
Concrete Agent Loop Driver and Factory Service mounted at `ctx.agent_loop`.
1:1 aligned with official `@deepseek-ai/dsh-agent-loop`.
"""

import asyncio
import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.core.agent import Agent, AgentHandle, AgentOptions, AgentRegistry
from dsh.core.runtime_context import RuntimeContextProjection
from dsh.core.session import Session, SessionHeader, SessionStore, canonical_header, header_equals
from dsh.core.tool_calls import execute_tool_calls
from dsh.core.tools import ToolsService


def request_proposal(header: Dict[str, Any]) -> Dict[str, Any]:
    """Remove adapter-derived values before plugins propose the next request config."""
    config = dict(header.get("config", {}))
    adapter_defaults = header.get("adapterDefaults", {})
    if adapter_defaults.get("reasoningEffort") is True:
        config.pop("reasoningEffort", None)
    if adapter_defaults.get("maxTokens") is True:
        config.pop("maxTokens", None)
    return config


class PartialBlock:
    def __init__(self, block_type: str):
        self.block_type = block_type
        self.text: str = ""
        self.tool_call_id: Optional[str] = None
        self.tool_call_name: Optional[str] = None
        self.tool_call_arguments: str = ""


class BlockAssembler:
    """
    Incremental chunk-to-message assembler.
    1:1 aligned with official `@deepseek-ai/dsh-llm/assembler`.
    """

    def __init__(self):
        self._partials: Dict[int, PartialBlock] = {}
        self._order: List[int] = []
        self.usage: Optional[Dict[str, Any]] = None
        self.timing: Optional[Dict[str, Any]] = None
        self.finish_kind: str = "completed"
        self.failure: Optional[Dict[str, Any]] = None

    def _ensure(self, index: int, block_type: str) -> PartialBlock:
        if index not in self._partials:
            self._partials[index] = PartialBlock(block_type=block_type)
            self._order.append(index)
        return self._partials[index]

    def push(self, chunk: Any) -> None:
        if isinstance(chunk, str):
            if chunk:
                partial = self._ensure(0, "text")
                partial.text += chunk
            return

        if not isinstance(chunk, dict):
            return

        ctype = chunk.get("type")
        if ctype == "block-start":
            idx = chunk.get("index", 0)
            btype = chunk.get("blockType", "text")
            self._ensure(idx, btype)
            return

        if ctype == "text-delta":
            idx = chunk.get("index", 0)
            text = chunk.get("text", "")
            partial = self._ensure(idx, "text")
            partial.text += text
            return

        if ctype == "reasoning-delta":
            idx = chunk.get("index", 1)
            text = chunk.get("text", "")
            partial = self._ensure(idx, "reasoning")
            partial.text += text
            return

        if ctype == "tool-call-delta":
            idx = chunk.get("index", 10)
            partial = self._ensure(idx, "tool-call")
            if chunk.get("id"):
                partial.tool_call_id = chunk["id"]
            if chunk.get("name"):
                partial.tool_call_name = chunk["name"]
            if chunk.get("argumentsDelta"):
                partial.tool_call_arguments += chunk["argumentsDelta"]
            return

        if ctype == "block-end":
            idx = chunk.get("index", 0)
            block = chunk.get("block", {})
            if isinstance(block, dict):
                btype = block.get("type", "text")
                partial = self._ensure(idx, btype)
                if btype in ("text", "reasoning") and "text" in block:
                    partial.text = block["text"]
                elif btype == "tool-call":
                    if block.get("id"):
                        partial.tool_call_id = block["id"]
                    if block.get("name"):
                        partial.tool_call_name = block["name"]
                    if block.get("arguments") is not None:
                        args = block["arguments"]
                        partial.tool_call_arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            return

        if ctype == "usage":
            if "usage" in chunk and isinstance(chunk["usage"], dict):
                self.usage = chunk["usage"]
            return

        if ctype == "finish":
            reason = chunk.get("reason", {})
            kind = reason.get("kind") if isinstance(reason, dict) else str(reason)
            if kind == "max-tokens":
                self.finish_kind = "max-tokens"
            return

        if "message" in chunk and isinstance(chunk["message"], dict):
            msg = chunk["message"]
            content = msg.get("content")
            if content and isinstance(content, str):
                partial = self._ensure(0, "text")
                if not partial.text:
                    partial.text = content
            tcalls = msg.get("tool_calls")
            if tcalls and isinstance(tcalls, list):
                for idx, tc in enumerate(tcalls):
                    partial = self._ensure(100 + idx, "tool-call")
                    cid = tc.get("id") or str(tc.get("index", idx))
                    func = tc.get("function", {}) if "function" in tc else tc
                    name = func.get("name", "")
                    args = func.get("arguments", "")
                    partial.tool_call_id = cid
                    partial.tool_call_name = name
                    partial.tool_call_arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)

        if "usage" in chunk and isinstance(chunk["usage"], dict):
            self.usage = chunk["usage"]
        if "timing" in chunk and isinstance(chunk["timing"], dict):
            self.timing = chunk["timing"]

        finish_reason = chunk.get("finish_reason") or chunk.get("reason")
        if finish_reason == "length" or finish_reason == "max_tokens":
            self.finish_kind = "max-tokens"

        delta = chunk.get("delta") or chunk.get("choices", [{}])[0].get("delta", {})
        if not isinstance(delta, dict):
            return

        text_delta = delta.get("content") or delta.get("text")
        if text_delta and isinstance(text_delta, str):
            partial = self._ensure(0, "text")
            partial.text += text_delta

        reasoning_delta = delta.get("reasoning_content") or delta.get("reasoning")
        if reasoning_delta and isinstance(reasoning_delta, str):
            partial = self._ensure(1, "reasoning")
            partial.text += reasoning_delta

        tool_calls = delta.get("tool_calls")
        if tool_calls and isinstance(tool_calls, list):
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                tc_idx = tc.get("index", 0) + 10
                partial = self._ensure(tc_idx, "tool-call")
                cid = tc.get("id")
                if cid:
                    partial.tool_call_id = cid
                func = tc.get("function", {}) if "function" in tc else tc
                name = func.get("name")
                if name:
                    partial.tool_call_name = name
                args_delta = func.get("arguments") or tc.get("arguments", "")
                if args_delta and isinstance(args_delta, str):
                    partial.tool_call_arguments += args_delta

    def _assemble_partial(self, index: int, partial: PartialBlock) -> Dict[str, Any]:
        if partial.block_type == "text":
            return {"type": "text", "text": partial.text}
        elif partial.block_type == "reasoning":
            return {"type": "reasoning", "text": partial.text}
        elif partial.block_type == "tool-call":
            return {
                "type": "tool-call",
                "id": partial.tool_call_id or f"call-{index}",
                "name": partial.tool_call_name or "",
                "arguments": partial.tool_call_arguments,
            }
        return {"type": "text", "text": partial.text}

    def blocks(self) -> List[Dict[str, Any]]:
        all_blocks = [self._assemble_partial(idx, self._partials[idx]) for idx in self._order]
        if self.finish_kind == "max-tokens":
            # Truncation drops tool calls that cannot be executed safely
            return [b for b in all_blocks if b.get("type") != "tool-call"]
        return all_blocks

    def interrupted_blocks(self) -> List[Dict[str, Any]]:
        result = []
        for idx in self._order:
            partial = self._partials[idx]
            if partial.block_type in ("text", "reasoning") and partial.text.strip():
                result.append(self._assemble_partial(idx, partial))
        return result


class AgentLoopService:
    """
    Concrete Agent Factory and Asynchronous Driver Service mounted at `ctx.agent_loop`.
    """

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self._turn_counters: Dict[str, int] = {}
        self._active_tasks: List[asyncio.Task] = []
        self._default_agent: Optional[Agent] = None
        self._request_header_logged: Dict[str, bool] = {}

    def _get_turn_number(self, agent_id: str) -> int:
        self._turn_counters[agent_id] = self._turn_counters.get(agent_id, 0) + 1
        return self._turn_counters[agent_id]

    async def create_agent(
        self,
        session_id: Optional[str] = None,
        options: Optional[AgentOptions] = None,
        meta: Optional[Dict[str, Any]] = None,
        setup: Optional[Callable[[Context], Any]] = None,
    ) -> AgentHandle:
        sid = session_id or f"session-{uuid.uuid4().hex[:8]}"

        sessions_svc = self.ctx.get("sessions")
        if isinstance(sessions_svc, SessionStore):
            session = sessions_svc.get(sid) or sessions_svc.create(sid, meta=meta)
        else:
            header = SessionHeader.from_dict({"id": sid, **(meta or {})})
            session = Session(session_id=sid, header=header, ctx=self.ctx)

        agent_ctx = self.ctx.extend()
        commit_fn = None
        if setup:
            setup_res = setup(agent_ctx)
            if hasattr(setup_res, "commit") and callable(getattr(setup_res, "commit")):
                commit_fn = setup_res.commit

        if commit_fn:
            commit_fn()

        agent = Agent(session=session, options=options, ctx=agent_ctx)

        agents_svc: Optional[AgentRegistry] = self.ctx.get("agents")
        disposer = None
        if agents_svc:
            disposer = agents_svc.register(agent)

        driver_task = asyncio.create_task(self._drive_agent(agent))
        self._active_tasks.append(driver_task)
        agent._driver_task = driver_task

        async def teardown() -> None:
            agent.cancel({"kind": "disposed"})
            if not driver_task.done():
                await agent.when_idle()
                driver_task.cancel()
            agent_ctx.teardown()
            if disposer:
                disposer()

        return AgentHandle(agent=agent, disposer=teardown)

    async def resume(
        self,
        resume_session_id: str,
        options: Optional[AgentOptions] = None,
        setup: Optional[Callable[[Context], Any]] = None,
    ) -> AgentHandle:
        persistence = self.ctx.get("session_persistence")
        if not persistence:
            raise RuntimeError("no session_persistence service configured for resume")

        inspection = await persistence.load(resume_session_id)
        session = Session.from_restore(
            session_id=resume_session_id,
            seed=inspection.events,
            header=inspection.meta,
            ctx=self.ctx,
        )

        agent_ctx = self.ctx.extend()
        commit_fn = None
        if setup:
            setup_res = setup(agent_ctx)
            if hasattr(setup_res, "commit") and callable(getattr(setup_res, "commit")):
                commit_fn = setup_res.commit

        if commit_fn:
            commit_fn()

        agent = Agent(session=session, options=options, ctx=agent_ctx)

        agents_svc: Optional[AgentRegistry] = self.ctx.get("agents")
        disposer = None
        if agents_svc:
            disposer = agents_svc.register(agent)

        driver_task = asyncio.create_task(self._drive_agent(agent))
        self._active_tasks.append(driver_task)
        agent._driver_task = driver_task

        async def teardown() -> None:
            agent.cancel({"kind": "disposed"})
            if not driver_task.done():
                await agent.when_idle()
                driver_task.cancel()
            agent_ctx.teardown()
            if disposer:
                disposer()

        return AgentHandle(agent=agent, disposer=teardown)

    async def _drive_agent(self, agent: Agent) -> None:
        """Background driver loop pumping the agent's inbox."""
        try:
            while True:
                if agent.is_cancelled():
                    cause = agent.take_cancel_cause()
                    agent.session.append("turn/end", {"turn": getattr(agent, "_last_turn", 0), "reason": {"kind": "aborted", "cause": cause}}, ignorable=True)
                    agent.set_status("idle")

                if agent.inbox.is_empty():
                    agent.set_status("idle")
                    await agent._wake_event.wait()
                    agent._wake_event.clear()
                    continue

                agent.set_phase("running")

                agents_svc: Optional[AgentRegistry] = self.ctx.get("agents")
                if agents_svc:
                    await agents_svc.with_initiator_async(agent, self._kick(agent))
                else:
                    await self._kick(agent)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger = getattr(self.ctx, "logger", None)
            if logger and hasattr(logger, "error"):
                logger.error("agent driver crashed: %s", str(e))
        finally:
            agent.set_status("idle")

    async def _kick(self, agent: Agent) -> None:
        try:
            while await self._turn(agent):
                pass
        except Exception:
            pass
        finally:
            agent.set_status("idle")

    async def _turn(self, agent: Agent) -> bool:
        session = agent.session
        turn_num = self._get_turn_number(agent.id)
        setattr(agent, "_last_turn", turn_num)
        session.append("turn/start", {"turn": turn_num}, ignorable=True)

        turn_ends: Optional[Dict[str, Any]] = None
        target = "next-turn"
        step_num = 0

        runtime_context_proj = RuntimeContextProjection(agent.ctx, session)

        try:
            while True:
                if agent.is_cancelled():
                    cause = agent.take_cancel_cause()
                    turn_ends = {"kind": "aborted", "reason": cause}
                    break

                step_num += 1

                claimed = agent.inbox.claim(target=target, turn=turn_num)

                system_prompt = "You are a helpful software engineer assistant."
                persona = self.ctx.get("persona")
                if persona and hasattr(persona, "get_prompt"):
                    system_prompt = persona.get_prompt()

                system_prompt = await self.ctx.waterfall("system-prompt/assemble", system_prompt)
                system_prompt = await self.ctx.waterfall("agent/prompt-assemble", system_prompt)

                request_payload = {
                    "agent": agent,
                    "messages": claimed,
                    "turn": turn_num,
                    "step": step_num,
                }
                pre_step_res = await self.ctx.waterfall("agent/pre-step", request_payload)

                if isinstance(pre_step_res, dict) and pre_step_res.get("kind") == "reject":
                    turn_ends = {"kind": "blocked"}
                    return False

                for msg in claimed:
                    session.append_user_message(msg.get("content", ""), source=msg.get("source"))

                candidate_ctx = runtime_context_proj.project(system_prompt, [])
                if candidate_ctx:
                    session.append("user/message", candidate_ctx, surface_op="append")

                if step_num == 1 and not claimed and len(session.surface.nodes) == 0:
                    turn_ends = {"kind": "completed"}
                    return False

                session.append("step/start", {"turn": turn_num, "step": step_num}, ignorable=True)

                try:
                    step_end = await self._step(agent, turn_num, step_num, system_prompt)
                    if step_end:
                        if turn_ends is None or turn_ends.get("kind") != "max-tokens":
                            turn_ends = step_end
                finally:
                    session.append("step/end", {"turn": turn_num, "step": step_num}, ignorable=True)

                if turn_ends and len(agent.inbox.next_step) == 0:
                    await self.ctx.serial("agent/turn-stopping", {"turn": turn_num, "agent": agent})

                if turn_ends and len(agent.inbox.next_step) == 0:
                    break
                elif turn_ends and len(agent.inbox.next_step) > 0:
                    turn_ends = None

                target = "next-step"

        except Exception as e:
            if agent.is_cancelled():
                turn_ends = {"kind": "aborted", "reason": agent.take_cancel_cause()}
                raise
            turn_ends = {"kind": "error", "error": {"message": str(e), "code": "UNKNOWN"}}
            raise
        finally:
            final_reason = turn_ends or {"kind": "completed"}
            session.append("turn/end", {"turn": turn_num, "reason": final_reason}, ignorable=True)
            self.ctx.emit("agent/turn-stopped", {"agent": agent, "turn": turn_num, "session": session})
            await session.flush()

        return agent.inbox.has_pending

    async def _step(self, agent: Agent, turn: int, step: int, system_prompt: str) -> Optional[Dict[str, Any]]:
        session = agent.session
        llm_service = self.ctx.get("llm")
        tools_service = self.ctx.get("tools")
        tool_schemas = tools_service.get_schemas() if tools_service else []

        raw_provider = agent.options.provider or getattr(llm_service, "provider", "openai")
        raw_model = agent.options.model or getattr(llm_service, "model", "deepseek-chat")
        provider_name = str(raw_provider) if raw_provider is not None else "openai"
        model_name = str(raw_model) if raw_model is not None else "deepseek-chat"

        persisted_header = session.request_header()
        persisted_config = persisted_header.get("config", {}) if persisted_header else {}
        logged_before = self._request_header_logged.get(agent.id, False)

        seed_config = (
            request_proposal(persisted_header)
            if logged_before and persisted_header
            else {
                "provider": provider_name,
                "model": model_name,
                **({"maxTokens": agent.options.max_tokens} if agent.options.max_tokens is not None else {}),
            }
        )

        proposed_config = await self.ctx.waterfall("agent/request", seed_config)
        if isinstance(proposed_config, dict):
            provider_name = str(proposed_config.get("provider", provider_name))
            model_name = str(proposed_config.get("model", model_name))

        header_data = canonical_header({
            "system": system_prompt,
            "tools": tool_schemas,
            "config": {"provider": provider_name, "model": model_name},
        })

        baseline_header = session.request_header()
        if not logged_before:
            reason = "initial" if baseline_header is None else "resume"
            session.append_request_header(header_data, reason=reason)
            self._request_header_logged[agent.id] = True
        elif baseline_header is None or not header_equals(baseline_header, header_data):
            session.append_request_header(header_data, reason="change")

        baseline_ctx = session.request_context()
        if (
            baseline_ctx is None
            or baseline_ctx.get("provider") != provider_name
            or baseline_ctx.get("model") != model_name
        ):
            session.append_request_context(provider=provider_name, model=model_name, context_window=128000)

        messages = session.derive_messages(system_prompt=system_prompt)

        if not llm_service:
            raise RuntimeError("LLM service ('ctx.llm') is missing")

        assembler = BlockAssembler()
        chunk_seqs: List[int] = []

        try:
            stream_fn = getattr(llm_service, "chat_completion_stream", None)
            used_stream = False
            if stream_fn and callable(stream_fn):
                try:
                    stream_iter = stream_fn(messages=messages, tools=tool_schemas if tool_schemas else None)
                    for chunk in stream_iter:
                        # TS port yields StreamChunk dict; legacy tuple (ev_type, ev_payload) also supported
                        if isinstance(chunk, (list, tuple)) and len(chunk) == 2:
                            ev_type, ev_payload = chunk
                            if ev_type == "chunk":
                                ev_payload = ev_payload
                            elif ev_type == "finish":
                                assembler.push(ev_payload)
                                used_stream = True
                                continue
                            else:
                                ev_payload = chunk
                        else:
                            ev_payload = chunk
                        # Treat every StreamChunk dict as a chunk
                        if not isinstance(ev_payload, dict):
                            continue
                        chunk_payload = {
                            "turn": turn,
                            "step": step,
                            "chunk": ev_payload,
                            **ev_payload,
                        }
                        chunk_ev = session.append(
                            "assistant/chunk",
                            chunk_payload,
                            ignorable=True,
                        )
                        seq = chunk_ev.get("seq", 0) if isinstance(chunk_ev, dict) else getattr(chunk_ev, "seq", 0)
                        chunk_seqs.append(seq)
                        assembler.push(ev_payload)
                        self.ctx.emit("session/chunk", session, chunk_ev)
                        self.ctx.emit("assistant/chunk", chunk_ev)
                        if ev_payload.get("type") == "finish":
                            used_stream = True
                    # If we completed iteration without exception, mark streamed
                    if chunk_seqs or assembler._order:
                        used_stream = True
                except asyncio.CancelledError:
                    content = assembler.interrupted_blocks()
                    if content:
                        session.append_assistant_message(
                            {"content": content, "role": "assistant"},
                            turn=turn,
                            step=step,
                            surface_op="append",
                            source_event_seqs=chunk_seqs if chunk_seqs else None,
                        )
                    raise
                except Exception as e:
                    # Streaming failed -> fallback to non-stream; keep assembler if partial streamed
                    if not assembler._order and not chunk_seqs:
                        used_stream = False
                    else:
                        # Partial stream succeeded, treat as streamed
                        used_stream = True
                        # Suppress exception if we already have content
                        pass

            if not used_stream:
                sync_res = llm_service.chat_completion(
                    messages=messages,
                    tools=tool_schemas if tool_schemas else None,
                )
                if isinstance(sync_res, dict):
                    content = sync_res.get("content", "")
                    tcalls = sync_res.get("tool_calls", [])
                    msg_blocks = []
                    if content:
                        msg_blocks.append({"type": "text", "text": content})
                    if tcalls:
                        for tc in tcalls:
                            func = tc.get("function", {}) if "function" in tc else tc
                            msg_blocks.append({
                                "type": "tool-call",
                                "id": tc.get("id", ""),
                                "name": func.get("name", ""),
                                "arguments": func.get("arguments", "{}"),
                            })
                    assembler._partials[0] = PartialBlock("text")
                    assembler._partials[0].text = content if isinstance(content, str) else ""
                    assembler._order = [0]
                    if tcalls:
                        for idx, tc in enumerate(tcalls):
                            p = PartialBlock("tool-call")
                            p.tool_call_id = tc.get("id", "")
                            func = tc.get("function", {}) if "function" in tc else tc
                            p.tool_call_name = func.get("name", "")
                            p.tool_call_arguments = func.get("arguments", "{}")
                            assembler._partials[10 + idx] = p
                            assembler._order.append(10 + idx)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            failure_payload = {
                "message": str(e),
                "code": getattr(e, "code", "UNKNOWN"),
            }
            recovery = await self.ctx.waterfall(
                "agent/request-error",
                {
                    "agent": agent,
                    "error": str(e),
                    "failure": failure_payload,
                    "provider": provider_name,
                    "turn": turn,
                    "step": step,
                },
            )
            if isinstance(recovery, dict) and recovery.get("kind") == "retry":
                return await self._step(agent, turn, step, system_prompt)
            raise

        blocks = assembler.blocks()
        assistant_msg = {
            "role": "assistant",
            "content": blocks if blocks else [{"type": "text", "text": ""}],
        }
        tool_calls = [b for b in blocks if b.get("type") == "tool-call"]
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls

        session.append_assistant_message(
            assistant_msg,
            turn=turn,
            step=step,
            usage=assembler.usage,
            timing=assembler.timing,
            surface_op="append",
            source_event_seqs=chunk_seqs if chunk_seqs else None,
        )

        if assembler.finish_kind == "max-tokens":
            return {"kind": "max-tokens"}

        if not tool_calls:
            return {"kind": "completed"}

        outcome = await execute_tool_calls(
            ctx=self.ctx,
            agent=agent,
            turn=turn,
            step=step,
            tool_calls=tool_calls,
            signal=getattr(agent, "_cancel_event", None),
            accept_context=lambda ctx_item: agent.inbox.splice("next-step", len(agent.inbox.next_step), 0, [ctx_item]),
        )

        return {"kind": "completed"} if outcome.get("concluded") else None

    async def run_turn(self, user_input: str, max_steps: int = 10) -> str:
        """Backward-compatible run_turn helper."""
        if self._default_agent is None:
            handle = await self.create_agent("default-session")
            self._default_agent = handle.agent

        agent = self._default_agent
        agent.followup(user_input)
        await agent.when_idle()

        for event in reversed(agent.session.events):
            if event.get("type") == "assistant/message":
                msg = event.get("data", {}).get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    if texts:
                        return "".join(texts)
        return ""

    def teardown(self) -> None:
        for t in self._active_tasks:
            if not t.done():
                t.cancel()
        self._active_tasks.clear()


class AgentLoopPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-agent-loop`: Core agent loop & factory driver.
    """

    id = "agent-loop"
    name = "@deepseek-ai/dsh-agent-loop"

    def apply(self, ctx: Context) -> None:
        if not ctx.has("tools"):
            ctx.set_service("tools", ToolsService(ctx))

        if not ctx.has("sessions"):
            store = SessionStore(ctx=ctx)
            ctx.set_service("sessions", store)

        if not ctx.has("agents"):
            registry = AgentRegistry(ctx=ctx)
            ctx.set_service("agents", registry)

        agent_loop = AgentLoopService(ctx)
        ctx.set_service("agent_loop", agent_loop)

        registry = ctx.get("agents")
        if registry:
            registry.set_factory(agent_loop)

        ctx.effect(agent_loop.teardown)
