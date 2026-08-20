import asyncio
import uuid
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.core.session import Session, SessionStore
from dsh.core.tools import ToolsService


class AgentLoopService:
    """
    Agent Turn & Step Loop Service mounted at `ctx.agent_loop`.
    Manages agent lifecycle events, multi-step turn execution, request header logging,
    and durability flush checkpoints.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._turn_count = 0

    def _resolve_session(self) -> Optional[Session]:
        sessions_svc = self.ctx.get("sessions")
        if isinstance(sessions_svc, SessionStore):
            s = sessions_svc.get("default-session")
            if not s:
                s = sessions_svc.create("default-session")
            return s
        elif isinstance(sessions_svc, Session):
            return sessions_svc
        return None

    async def run_turn(self, user_input: str, max_steps: int = 10) -> str:
        """
        Run a complete agent turn for user input.
        """
        self._turn_count += 1
        turn_num = self._turn_count

        # Event: turn/start
        self.ctx.emit("turn/start", user_input)

        session = self._resolve_session()
        if session:
            session.append("turn/start", {"turn": turn_num}, ignorable=True)
            session.append_user_message(user_input)

        step_count = 0
        final_response = ""

        while step_count < max_steps:
            step_count += 1
            # Event: step/start
            self.ctx.emit("step/start", step_count)
            if session:
                session.append("step/start", {"turn": turn_num, "step": step_count}, ignorable=True)

            # Assemble system prompt
            system_prompt = "You are a helpful software engineer assistant."
            persona = self.ctx.get("persona")
            if persona and hasattr(persona, "get_prompt"):
                system_prompt = persona.get_prompt()

            # Trigger waterfall: agent/prompt-assemble
            system_prompt = await self.ctx.waterfall("agent/prompt-assemble", system_prompt)

            # Derive messages from session
            if session:
                messages = session.derive_messages(system_prompt=system_prompt)
            else:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ]

            # Gather tools schemas
            tools_service = self.ctx.get("tools")
            tool_schemas = tools_service.get_schemas() if tools_service else []

            request_payload = {
                "messages": messages,
                "tools": tool_schemas if tool_schemas else None,
            }

            # Record request/header and request/context
            llm_service = self.ctx.get("llm")
            if llm_service:
                model_name = getattr(llm_service, "model", "deepseek-chat")
                if session:
                    session.append_request_header({
                        "system": system_prompt,
                        "tools": tool_schemas,
                        "config": {"provider": "openai", "model": model_name},
                    })
                    session.append_request_context(provider="openai", model=model_name, context_window=128000)

            # Event: agent/pre-step (waterfall for compaction, pruner, or middleware)
            request_payload = await self.ctx.waterfall("agent/pre-step", request_payload)

            if not llm_service:
                raise RuntimeError("LLM service ('ctx.llm') is missing")

            # Call LLM API
            assistant_msg = llm_service.chat_completion(
                messages=request_payload["messages"],
                tools=request_payload.get("tools"),
            )

            if session:
                session.append_assistant_message(
                    assistant_msg,
                    turn=turn_num,
                    step=step_count,
                )

            tool_calls = assistant_msg.get("tool_calls")

            if not tool_calls:
                # No tool calls: assistant responded with text
                final_response = assistant_msg.get("content", "")
                if session:
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
                        import json
                        args = json.loads(args_raw)
                    else:
                        args = args_raw
                except Exception:
                    args = {}

                # Execute tool via ToolsService
                if tools_service:
                    result = await tools_service.execute_tool(name, args)
                else:
                    result = "Error: Tools service unavailable"

                if session:
                    session.append_tool_result(
                        tool_call_id=call_id,
                        name=name,
                        result=result,
                        turn=turn_num,
                        step=step_count,
                    )

            if session:
                session.append("step/end", {"turn": turn_num, "step": step_count}, ignorable=True)

        # Event: agent/turn-stopping & turn/end
        await self.ctx.serial("agent/turn-stopping")
        self.ctx.emit("turn/end", final_response)

        if session:
            session.append(
                "turn/end",
                {"turn": turn_num, "reason": {"kind": "completed"}},
                ignorable=True,
            )
            await session.flush()

        return final_response


class AgentLoopPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-agent-loop`: Core agent loop & session services.
    """

    id = "agent-loop"
    name = "@deepseek-ai/dsh-agent-loop"

    def apply(self, ctx: Any) -> None:
        if not ctx.has("tools"):
            ctx.set_service("tools", ToolsService(ctx))

        if not ctx.has("sessions"):
            store = SessionStore(ctx=ctx)
            ctx.set_service("sessions", store)

        agent_loop = AgentLoopService(ctx)
        ctx.set_service("agent_loop", agent_loop)
