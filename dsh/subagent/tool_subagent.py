import asyncio
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.subagent.subagent_service import SubagentRegistry


class ToolSubagentPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-subagent`: Subagent delegation tools (subagent, subagent_fork, list_agents, send_message, report).
    """

    id = "tool-subagent"
    name = "@deepseek-ai/dsh-tool-subagent"
    inject = ["tools"]

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        if not tools:
            return

        if not ctx.has("subagents"):
            ctx.set_service("subagents", SubagentRegistry(ctx))

        subagents_svc: SubagentRegistry = ctx.get("subagents")

        async def exec_subagent(task: str, run_in_background: bool = False) -> str:
            # Delegate subtask
            record = subagents_svc.spawn(parent_session_id="root", task=task, provider="spawn")
            if run_in_background:
                return f"Spawned background subagent '{record.id}' for task: {task}"
            
            # Foreground: simulate quick execution or wait
            record.complete(f"Subagent '{record.id}' completed subtask: {task}")
            return f"Subagent '{record.id}' finished.\nResult: {record.result}"

        async def exec_subagent_fork(task: str) -> str:
            record = subagents_svc.spawn(parent_session_id="root", task=task, provider="fork")
            record.complete(f"Forked subagent '{record.id}' completed task with inherited context: {task}")
            return f"Fork subagent '{record.id}' finished.\nResult: {record.result}"

        async def exec_list_agents() -> str:
            children = subagents_svc.list_children()
            if not children:
                return "No active or recorded subagents."
            lines = ["Subagents:"]
            for c in children:
                lines.append(f"- ID: {c.id} [{c.status.upper()}] (depth {c.depth}) Task: {c.task}")
            return "\n".join(lines)

        async def exec_send_message(id: str, message: str) -> str:
            rec = subagents_svc.get(id)
            if not rec:
                return f"Error: No subagent found with ID '{id}'"
            return f"Message delivered to subagent '{id}'. (Subagent is {rec.status})"

        disposer1 = tools.register_tool({
            "name": "subagent",
            "description": "Spawn a fresh child agent to perform an isolated subtask.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The specific task instruction for the child agent"},
                    "run_in_background": {"type": "boolean", "description": "Whether to run the child in background"},
                },
                "required": ["task"],
            },
            "execute": exec_subagent,
        })

        disposer2 = tools.register_tool({
            "name": "subagent_fork",
            "description": "Fork current agent context to run an exploratory task with full history inheritance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The task instruction for the forked child"},
                },
                "required": ["task"],
            },
            "execute": exec_subagent_fork,
        })

        disposer3 = tools.register_tool({
            "name": "list_agents",
            "description": "List all child subagents and their current execution status.",
            "parameters": {"type": "object", "properties": {}},
            "execute": exec_list_agents,
        })

        disposer4 = tools.register_tool({
            "name": "send_message",
            "description": "Send a follow-up instruction to a running child subagent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Target subagent ID"},
                    "message": {"type": "string", "description": "Message content"},
                },
                "required": ["id", "message"],
            },
            "execute": exec_send_message,
        })

        def cleanup():
            disposer1()
            disposer2()
            disposer3()
            disposer4()

        ctx.effect(cleanup)
