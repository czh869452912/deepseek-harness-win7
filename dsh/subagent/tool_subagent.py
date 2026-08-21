import asyncio
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.subagent.subagent_service import SubagentRegistry


class ToolSubagentPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-subagent` & `@deepseek-ai/dsh-tool-subagent-control`:
    Subagent delegation tools (`subagent`, `subagent_fork`, `send_message`, `interrupt_agent`, `list_agents`).
    """

    id = "tool-subagent"
    name = "@deepseek-ai/dsh-tool-subagent"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.background_mode: str = cfg.get("backgroundMode", "one-shot")
        self.enable_run_in_background: bool = cfg.get("enableRunInBackground", True)

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        if not tools:
            return

        if not ctx.has("subagents"):
            ctx.set_service("subagents", SubagentRegistry(ctx))

        subagents_svc: SubagentRegistry = ctx.get("subagents")

        async def exec_subagent(
            description: Optional[str] = None,
            prompt: Optional[str] = None,
            task: Optional[str] = None,
            run_in_background: Optional[bool] = None,
        ) -> str:
            actual_task = prompt or task or description or "General task"
            actual_desc = description or actual_task[:30]

            is_bg = run_in_background if run_in_background is not None else (self.background_mode == "continuable")

            if is_bg:
                if self.background_mode == "continuable":
                    started = subagents_svc.start_continuable(parent_session_id="root", task=actual_task, provider="spawn")
                    return f"started subagent {started['childId']}"
                else:
                    record = subagents_svc.spawn(parent_session_id="root", task=actual_task, provider="spawn")
                    return f"started background subagent job {record.id}"

            record = subagents_svc.spawn(parent_session_id="root", task=actual_task, provider="spawn")
            record.complete(f"Subagent '{record.id}' completed subtask: {actual_task}")
            return f"Subagent '{record.id}' finished.\nResult: {record.result}"

        async def exec_subagent_fork(
            description: Optional[str] = None,
            prompt: Optional[str] = None,
            task: Optional[str] = None,
            run_in_background: Optional[bool] = None,
        ) -> str:
            actual_task = prompt or task or description or "Forked task"
            actual_desc = description or actual_task[:30]

            is_bg = run_in_background if run_in_background is not None else (self.background_mode == "continuable")

            if is_bg:
                if self.background_mode == "continuable":
                    started = subagents_svc.start_continuable(parent_session_id="root", task=actual_task, provider="fork")
                    return f"started subagent {started['childId']}"
                else:
                    record = subagents_svc.fork(parent_session_id="root", task=actual_task)
                    return f"started background subagent job {record.id}"

            record = subagents_svc.fork(parent_session_id="root", task=actual_task)
            record.complete(f"Forked subagent '{record.id}' completed task with inherited context: {actual_task}")
            return f"Fork subagent '{record.id}' finished.\nResult: {record.result}"

        async def exec_list_agents() -> str:
            children = subagents_svc.list_children()
            if not children:
                return "No active or recorded subagents."
            lines = ["Subagents:"]
            for c in children:
                lines.append(f"- ID: {c.id} [{c.status.upper()}] (depth {c.depth}) Task: {c.task}")
            return "\n".join(lines)

        async def exec_send_message(
            message: str,
            subagent_id: Optional[str] = None,
            id: Optional[str] = None,
        ) -> str:
            target_id = subagent_id or id
            if not target_id:
                return "Error: subagent_id is required"
            try:
                msg_id = subagents_svc.followup(subagent_id=target_id, message=message)
                return f"message queued as the next turn for subagent {target_id} ({msg_id})"
            except ValueError as e:
                return f"Error: {e}"

        async def exec_interrupt_agent(
            agent_id: Optional[str] = None,
            subagent_id: Optional[str] = None,
            id: Optional[str] = None,
        ) -> str:
            target_id = agent_id or subagent_id or id
            if not target_id:
                return "Error: agent_id is required"
            ok = subagents_svc.interrupt(target_id)
            if ok:
                return f"interrupt requested for agent {target_id}"
            return f"Agent {target_id} is not running (accepted no-op)"

        disposer1 = tools.register_tool({
            "name": "subagent",
            "description": "Delegate a self-contained task to a subagent (a separate agent that works in its own context).",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "A short (3-5 word) description of the delegated task, for display."},
                    "prompt": {"type": "string", "description": "The complete, self-contained task for the subagent."},
                    "task": {"type": "string", "description": "Legacy alias for prompt."},
                    "run_in_background": {"type": "boolean", "description": "Whether to run as a background task."},
                },
            },
            "execute": exec_subagent,
        })

        disposer2 = tools.register_tool({
            "name": "subagent_fork",
            "description": "Delegate a task to a subagent that inherits this conversation (seeded with all completed turns so far).",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "A short (3-5 word) description of the delegated task, for display."},
                    "prompt": {"type": "string", "description": "The task for the subagent with inherited completed turns."},
                    "task": {"type": "string", "description": "Legacy alias for prompt."},
                    "run_in_background": {"type": "boolean", "description": "Whether to run in background."},
                },
            },
            "execute": exec_subagent_fork,
        })

        disposer3 = tools.register_tool({
            "name": "send_message",
            "description": "Send a message to a background subagent by its subagent id, continuing the same conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subagent_id": {"type": "string", "description": "The subagent id returned when the background subagent was started."},
                    "id": {"type": "string", "description": "Legacy alias for subagent_id."},
                    "message": {"type": "string", "description": "The message to deliver to the subagent."},
                },
                "required": ["message"],
            },
            "execute": exec_send_message,
        })

        disposer4 = tools.register_tool({
            "name": "interrupt_agent",
            "description": "Request cancellation of a background agent's current turn by its agent id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "The agent id of the running agent to interrupt."},
                },
                "required": ["agent_id"],
            },
            "execute": exec_interrupt_agent,
        })

        disposer5 = tools.register_tool({
            "name": "list_agents",
            "description": "List all child subagents and their current execution status.",
            "parameters": {"type": "object", "properties": {}},
            "execute": exec_list_agents,
        })

        def cleanup():
            disposer1()
            disposer2()
            disposer3()
            disposer4()
            disposer5()

        ctx.effect(cleanup)

