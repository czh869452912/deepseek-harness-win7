"""
Concrete Agent Loop Driver and Factory Service mounted at `ctx.agent_loop`.
Implements asynchronous inbox-driven turn execution, pre-step waterfall, tool dispatching,
and request error recovery.
"""

import asyncio
import json
import uuid
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.core.agent import Agent, AgentHandle, AgentOptions, AgentRegistry
from dsh.core.session import Session, SessionHeader, SessionStore
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

    def _get_turn_number(self, agent_id: str) -> int:
        self._turn_counters[agent_id] = self._turn_counters.get(agent_id, 0) + 1
        return self._turn_counters[agent_id]

    async def create_agent(
        self,
        session_id: Optional[str] = None,
        options: Optional[AgentOptions] = None,
        meta: Optional[Dict[str, Any]] = None,
        setup: Optional[Callable[[Context], None]] = None,
    ) -> AgentHandle:
        sid = session_id or f"session-{uuid.uuid4().hex[:8]}"

        # Resolve or create session
        sessions_svc = self.ctx.get("sessions")
        if isinstance(sessions_svc, SessionStore):
            session = sessions_svc.get(sid) or sessions_svc.create(sid, meta=meta)
        else:
            header = SessionHeader.from_dict({"id": sid, **(meta or {})})
            session = Session(session_id=sid, header=header, ctx=self.ctx)

        # Create scoped context
        agent_ctx = self.ctx.extend()
        if setup:
            setup(agent_ctx)

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
        setup: Optional[Callable[[Context], None]] = None,
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
        if setup:
            setup(agent_ctx)

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

                # Claim next batch: next_step items and 1 next_turn prompt
                claimed_batch = agent.inbox.claim(target="next-turn")
                if not claimed_batch:
                    continue

                agents_svc: Optional[AgentRegistry] = self.ctx.get("agents")
                if agents_svc:
                    await agents_svc.with_initiator_async(agent, self._run_agent_turn(agent, claimed_batch))
                else:
                    await self._run_agent_turn(agent, claimed_batch)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self.ctx.logger:
                self.ctx.logger.error("agent driver crashed: %s", str(e))
        finally:
            agent.set_status("idle")

    async def _run_agent_turn(self, agent: Agent, claimed_messages: List[Dict[str, Any]], max_steps: int = 10) -> None:
        session = agent.session
        turn_num = self._get_turn_number(agent.id)

        session.append("turn/start", {"turn": turn_num}, ignorable=True)
        for msg in claimed_messages:
            session.append_user_message(msg.get("content", ""), source=msg.get("source"))

        step_count = 0

        while step_count < max_steps:
            if agent.is_cancelled():
                cause = agent.take_cancel_cause()
                session.append("turn/end", {"turn": turn_num, "reason": {"kind": "aborted", "cause": cause}}, ignorable=True)
                break

            step_count += 1
            session.append("step/start", {"turn": turn_num, "step": step_count}, ignorable=True)

            # 1. Assemble system prompt
            system_prompt = "You are a helpful software engineer assistant."
            persona = self.ctx.get("persona")
            if persona and hasattr(persona, "get_prompt"):
                system_prompt = persona.get_prompt()

            system_prompt = await self.ctx.waterfall("agent/prompt-assemble", system_prompt)

            # 2. Derive messages from surface
            messages = session.derive_messages(system_prompt=system_prompt)

            # 3. Gather tools schemas
            tools_service = self.ctx.get("tools")
            tool_schemas = tools_service.get_schemas() if tools_service else []

            # 4. Record request/header and request/context
            llm_service = self.ctx.get("llm")
            provider_name = agent.options.provider or "openai"
            model_name = agent.options.model or getattr(llm_service, "model", "deepseek-chat")

            session.append_request_header({
                "system": system_prompt,
                "tools": tool_schemas,
                "config": {"provider": provider_name, "model": model_name},
            })
            session.append_request_context(provider=provider_name, model=model_name, context_window=128000)

            # 5. Pre-step waterfall (interception, compaction, pruner, steering)
            request_payload = {
                "agent": agent,
                "messages": messages,
                "tools": tool_schemas if tool_schemas else None,
                "turn": turn_num,
                "step": step_count,
            }

            pre_step_res = await self.ctx.waterfall("agent/pre-step", request_payload)
            if isinstance(pre_step_res, dict) and pre_step_res.get("kind") == "reject":
                session.append("step/end", {"turn": turn_num, "step": step_count}, ignorable=True)
                break

            if not llm_service:
                raise RuntimeError("LLM service ('ctx.llm') is missing")

            # 6. Call LLM API (streaming with live chunk events)
            assistant_msg: Dict[str, Any] = {}
            timing_data: Dict[str, Any] = {}
            usage_data: Dict[str, Any] = {}

            try:
                stream_fn = getattr(llm_service, "chat_completion_stream", None)
                used_stream = False
                if stream_fn and callable(stream_fn):
                    try:
                        stream_iter = stream_fn(
                            messages=request_payload["messages"],
                            tools=request_payload.get("tools"),
                        )
                        for ev_type, ev_payload in stream_iter:
                            if ev_type == "chunk":
                                chunk_event = {
                                    "type": "assistant/chunk",
                                    "sessionId": session.id,
                                    "data": {
                                        "turn": turn_num,
                                        "step": step_count,
                                        **ev_payload,
                                    }
                                }
                                self.ctx.emit("session/chunk", session, chunk_event)
                                self.ctx.emit("assistant/chunk", chunk_event)
                            elif ev_type == "finish":
                                assistant_msg = ev_payload.get("message", {})
                                timing_data = ev_payload.get("timing", {})
                                usage_data = ev_payload.get("usage", {})
                                used_stream = True
                    except Exception:
                        used_stream = False

                if not used_stream or not assistant_msg:
                    assistant_msg = llm_service.chat_completion(
                        messages=request_payload["messages"],
                        tools=request_payload.get("tools"),
                    )
            except Exception as e:
                # Dispatch agent/request-error
                recovery = await self.ctx.waterfall(
                    "agent/request-error",
                    {"agent": agent, "error": str(e), "turn": turn_num, "step": step_count},
                )
                if isinstance(recovery, dict) and recovery.get("kind") == "retry":
                    continue
                session.append("step/end", {"turn": turn_num, "step": step_count}, ignorable=True)
                session.append("turn/end", {"turn": turn_num, "reason": {"kind": "error", "error": str(e)}}, ignorable=True)
                break

            session.append_assistant_message(
                assistant_msg,
                turn=turn_num,
                step=step_count,
                usage=usage_data if usage_data else None,
                timing=timing_data if timing_data else None,
            )

            tool_calls = assistant_msg.get("tool_calls")
            if not tool_calls:
                session.append("step/end", {"turn": turn_num, "step": step_count}, ignorable=True)
                break

            # Execute tool calls
            for tcall in tool_calls:
                call_id = tcall.get("id") or str(uuid.uuid4())
                func = tcall.get("function", {})
                name = func.get("name", "")
                args_raw = func.get("arguments", "{}")

                try:
                    if isinstance(args_raw, str):
                        args = json.loads(args_raw)
                    else:
                        args = args_raw
                except Exception:
                    args = {}

                if tools_service:
                    result = await tools_service.execute_tool(name, args)
                else:
                    result = "Error: Tools service unavailable"

                session.append_tool_result(
                    tool_call_id=call_id,
                    name=name,
                    result=result,
                    turn=turn_num,
                    step=step_count,
                )

            session.append("step/end", {"turn": turn_num, "step": step_count}, ignorable=True)

        await self.ctx.serial("agent/turn-stopping")
        session.append("turn/end", {"turn": turn_num, "reason": {"kind": "completed"}}, ignorable=True)
        await session.flush()

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

        # Register agent factory to AgentRegistry
        registry = ctx.get("agents")
        if registry:
            registry.set_factory(agent_loop)

        ctx.effect(agent_loop.teardown)
