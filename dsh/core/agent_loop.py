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
from dsh.core.session import Session, SessionHeader, SessionStore
from dsh.core.tool_calls import execute_tool_calls
from dsh.core.tools import ToolsService


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

        # Resolve or create session
        sessions_svc = self.ctx.get("sessions")
        if isinstance(sessions_svc, SessionStore):
            session = sessions_svc.get(sid) or sessions_svc.create(sid, meta=meta)
        else:
            header = SessionHeader.from_dict({"id": sid, **(meta or {})})
            session = Session(session_id=sid, header=header, ctx=self.ctx)

        # Create unpublished scoped context
        agent_ctx = self.ctx.extend()
        commit_fn = None
        if setup:
            setup_res = setup(agent_ctx)
            if hasattr(setup_res, "commit") and callable(getattr(setup_res, "commit")):
                commit_fn = setup_res.commit

        if commit_fn:
            commit_fn()

        agent = Agent(session=session, options=options, ctx=agent_ctx)

        # Register to AgentRegistry
        agents_svc: Optional[AgentRegistry] = self.ctx.get("agents")
        disposer = None
        if agents_svc:
            disposer = agents_svc.register(agent)

        # Start driver task
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
        """
        Background driver loop pumping the agent's inbox.
        """
        try:
            while True:
                if agent.is_cancelled():
                    cause = agent.take_cancel_cause()
                    agent.session.append("turn/end", {"reason": {"kind": "aborted", "cause": cause}}, ignorable=True)
                    agent.set_status("idle")

                if agent.inbox.is_empty():
                    agent.set_status("idle")
                    await agent._wake_event.wait()
                    agent._wake_event.clear()
                    continue

                # We have pending work
                agent.set_status("running")

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
        session.append("turn/start", {"turn": turn_num}, ignorable=True)

        turn_ends: Optional[Dict[str, Any]] = None
        target = "next-turn"
        step_num = 0

        try:
            while True:
                if agent.is_cancelled():
                    cause = agent.take_cancel_cause()
                    turn_ends = {"kind": "aborted", "reason": cause}
                    break

                step_num += 1

                # 1. Claim inbox and assemble pre-step
                claimed = agent.inbox.claim(target=target, turn=turn_num)

                system_prompt = "You are a helpful software engineer assistant."
                persona = self.ctx.get("persona")
                if persona and hasattr(persona, "get_prompt"):
                    system_prompt = persona.get_prompt()

                system_prompt = await self.ctx.waterfall("system-prompt/assemble", system_prompt)
                system_prompt = await self.ctx.waterfall("agent/prompt-assemble", system_prompt)

                # Pre-step waterfall
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

                # Append user messages to session
                for msg in claimed:
                    session.append_user_message(msg.get("content", ""), source=msg.get("source"))

                # Empty initial boundary check
                if step_num == 1 and not claimed and len(session.surface.nodes) == 0:
                    turn_ends = {"kind": "completed"}
                    return False

                session.append("step/start", {"turn": turn_num, "step": step_num}, ignorable=True)

                try:
                    # Execute step
                    step_end = await self._step(agent, turn_num, step_num, system_prompt)
                    if step_end:
                        turn_ends = step_end
                finally:
                    session.append("step/end", {"turn": turn_num, "step": step_num}, ignorable=True)

                if turn_ends and len(agent.inbox.next_step) == 0:
                    await self.ctx.serial("agent/turn-stopping")

                if turn_ends and len(agent.inbox.next_step) == 0:
                    break

                target = "next-step"

        except Exception as e:
            if agent.is_cancelled():
                turn_ends = {"kind": "aborted", "reason": agent.take_cancel_cause()}
                raise
            turn_ends = {"kind": "error", "error": str(e)}
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

        provider_name = agent.options.provider or "openai"
        model_name = agent.options.model or getattr(llm_service, "model", "deepseek-chat")

        header_data = {
            "system": system_prompt,
            "tools": tool_schemas,
            "config": {"provider": provider_name, "model": model_name},
        }

        # Header deduplication against session.request_header()
        baseline_header = session.request_header()
        logged_before = self._request_header_logged.get(agent.id, False)

        if not logged_before:
            reason = "initial" if baseline_header is None else "resume"
            session.append_request_header(header_data, reason=reason)
            self._request_header_logged[agent.id] = True
        elif baseline_header != header_data:
            session.append_request_header(header_data, reason="change")

        # Context deduplication against session.request_context()
        baseline_ctx = session.request_context()
        if (
            baseline_ctx is None
            or baseline_ctx.get("provider") != provider_name
            or baseline_ctx.get("model") != model_name
        ):
            session.append_request_context(provider=provider_name, model=model_name, context_window=128000)

        # Derive surface messages
        messages = session.derive_messages(system_prompt=system_prompt)

        if not llm_service:
            raise RuntimeError("LLM service ('ctx.llm') is missing")

        assistant_msg: Dict[str, Any] = {}
        timing_data: Dict[str, Any] = {}
        usage_data: Dict[str, Any] = {}
        chunk_seqs: List[int] = []

        try:
            stream_fn = getattr(llm_service, "chat_completion_stream", None)
            used_stream = False
            if stream_fn and callable(stream_fn):
                try:
                    stream_iter = stream_fn(messages=messages, tools=tool_schemas if tool_schemas else None)
                    for ev_type, ev_payload in stream_iter:
                        if ev_type == "chunk":
                            chunk_payload = {
                                "turn": turn,
                                "step": step,
                                "chunk": ev_payload,
                                **(ev_payload if isinstance(ev_payload, dict) else {}),
                            }
                            chunk_ev = session.append(
                                "assistant/chunk",
                                chunk_payload,
                                ignorable=True,
                            )
                            seq = chunk_ev.get("seq", 0) if isinstance(chunk_ev, dict) else getattr(chunk_ev, "seq", 0)
                            chunk_seqs.append(seq)
                            self.ctx.emit("session/chunk", session, chunk_ev)
                            self.ctx.emit("assistant/chunk", chunk_ev)
                        elif ev_type == "finish":
                            assistant_msg = ev_payload.get("message", {})
                            timing_data = ev_payload.get("timing", {})
                            usage_data = ev_payload.get("usage", {})
                            used_stream = True
                except Exception:
                    used_stream = False

            if not used_stream or not assistant_msg:
                assistant_msg = llm_service.chat_completion(
                    messages=messages,
                    tools=tool_schemas if tool_schemas else None,
                )

        except Exception as e:
            recovery = await self.ctx.waterfall(
                "agent/request-error",
                {"agent": agent, "error": str(e), "turn": turn, "step": step},
            )
            if isinstance(recovery, dict) and recovery.get("kind") == "retry":
                return await self._step(agent, turn, step, system_prompt)
            raise

        session.append_assistant_message(
            assistant_msg,
            turn=turn,
            step=step,
            usage=usage_data if usage_data else None,
            timing=timing_data if timing_data else None,
            surface_op="append",
            source_event_seqs=chunk_seqs if chunk_seqs else None,
        )

        tool_calls = assistant_msg.get("tool_calls")
        if not tool_calls:
            return {"kind": "completed"}

        outcome = await execute_tool_calls(
            ctx=self.ctx,
            agent=agent,
            turn=turn,
            step=step,
            tool_calls=tool_calls,
            signal=getattr(agent, "_cancel_event", None),
            accept_context=lambda ctx_item: session.append_user_message(str(ctx_item)),
        )

        return {"kind": "completed"} if outcome.get("concluded") else None

    async def run_turn(self, user_input: str, max_steps: int = 10) -> str:
        """
        Backward-compatible run_turn helper.
        """
        if self._default_agent is None:
            handle = await self.create_agent("default-session")
            self._default_agent = handle.agent

        agent = self._default_agent
        agent.followup(user_input)
        await agent.when_idle()

        # Extract last assistant response text
        for event in reversed(agent.session.events):
            if event.get("type") == "assistant/message":
                msg = event.get("data", {}).get("message", {})
                content = msg.get("content", "")
                if content:
                    return content
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
