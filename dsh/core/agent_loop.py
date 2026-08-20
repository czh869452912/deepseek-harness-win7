import asyncio
import uuid
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.core.session import SessionService
from dsh.core.tools import ToolsService


class AgentLoopService:
    """
    Agent Turn & Step Loop Service mounted at `ctx.agent_loop`.
    Manages agent lifecycle events and multi-step turn execution.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def run_turn(self, user_input: str, max_steps: int = 10) -> str:
        """
        Run a complete agent turn for user input.
        """
        # Event: turn/start
        self.ctx.emit("turn/start", user_input)

        session_service = self.ctx.get("sessions")
        if session_service:
            session_service.append_user_message(user_input)

        step_count = 0
        final_response = ""

        while step_count < max_steps:
            step_count += 1
            # Event: step/start
            self.ctx.emit("step/start", step_count)

            # Assemble system prompt
            system_prompt = "You are a helpful software engineer assistant."
            persona = self.ctx.get("persona")
            if persona and hasattr(persona, "get_prompt"):
                system_prompt = persona.get_prompt()

            # Trigger waterfall: agent/prompt-assemble
            system_prompt = await self.ctx.waterfall("agent/prompt-assemble", system_prompt)

            # Derive messages from session
            messages = []
            if session_service:
                messages = session_service.derive_messages(system_prompt=system_prompt)
            else:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ]

            # Gather tools schemas
            tools_service = self.ctx.get("tools")
            tool_schemas = tools_service.get_schemas() if tools_service else []

            request_payload = {
                "messages": messages,
                "tools": tool_schemas if tool_schemas else None
            }

            # Event: agent/pre-step
            request_payload = await self.ctx.waterfall("agent/pre-step", request_payload)

            llm_service = self.ctx.get("llm")
            if not llm_service:
                raise RuntimeError("LLM service ('ctx.llm') is missing")

            # Call LLM API
            assistant_msg = llm_service.chat_completion(
                messages=request_payload["messages"],
                tools=request_payload.get("tools")
            )

            if session_service:
                session_service.append_assistant_message(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls")

            if not tool_calls:
                # No tool calls: assistant responded with text
                final_response = assistant_msg.get("content", "")
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
                except Exception as e:
                    args = {}

                # Execute tool via ToolsService
                if tools_service:
                    result = await tools_service.execute_tool(name, args)
                else:
                    result = f"Error: Tools service unavailable"

                if session_service:
                    session_service.append_tool_result(call_id, name, result)

            # Continue next step loop if tools were executed

        # Event: agent/turn-stopping & turn/end
        await self.ctx.serial("agent/turn-stopping")
        self.ctx.emit("turn/end", final_response)
        
        if session_service:
            await session_service.flush()

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
            ctx.set_service("sessions", SessionService(ctx=ctx))

        agent_loop = AgentLoopService(ctx)
        ctx.set_service("agent_loop", agent_loop)
