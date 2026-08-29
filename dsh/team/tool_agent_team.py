"""
Agent Teams model tools plugin matching @deepseek-ai/dsh-tool-agent-team.
Exposes team roster, taskboard, and mailbox tools to agents.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class ToolAgentTeamPlugin(Plugin):
    """Exposes Agent Teams tools to agents."""
    name = "tool-agent-team"
    id = "@deepseek-ai/dsh-tool-agent-team"
    inject = ["agentTeams"]

    def apply(self, ctx: Any) -> None:
        tools_svc = ctx.get("tools") if hasattr(ctx, "get") else getattr(ctx, "tools", None)
        team_svc = ctx.get("agentTeams") if hasattr(ctx, "get") else getattr(ctx, "agentTeams", None)
        if not tools_svc or not team_svc:
            return

        # 1. team_member_list
        def team_member_list() -> Dict[str, Any]:
            """List all members and roles currently in the team."""
            return {"members": team_svc.list_members()}

        # 2. team_task_create
        def team_task_create(subject: str, description: str = "", owner_id: Optional[str] = None) -> Dict[str, Any]:
            """Create a new task on the team task board."""
            task = team_svc.create_task(subject=subject, description=description, owner_id=owner_id)
            return {"task": task}

        # 3. team_task_claim
        def team_task_claim(task_id: str, owner_id: str) -> Dict[str, Any]:
            """Claim an existing task on the team task board."""
            task = team_svc.claim_task(task_id=task_id, owner_id=owner_id)
            return {"task": task}

        # 4. team_task_update
        def team_task_update(task_id: str, status: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
            """Update status or description of a team task."""
            task = team_svc.update_task(task_id=task_id, status=status, description=description)
            return {"task": task}

        # 5. team_task_list
        def team_task_list(status: Optional[str] = None) -> Dict[str, Any]:
            """List tasks from the team task board."""
            return {"tasks": team_svc.list_tasks(status=status)}

        # 6. team_send_mail
        def team_send_mail(sender_id: str, sender_name: str, target_id: str, content: str) -> Dict[str, Any]:
            """Send an asynchronous message to a teammate's mailbox."""
            msg = team_svc.send_mail(sender_id=sender_id, sender_name=sender_name, target_id=target_id, content=content)
            return {"message": msg}

        # 7. team_read_mail
        def team_read_mail(target_id: str) -> Dict[str, Any]:
            """Read incoming messages in an agent's mailbox."""
            messages = team_svc.read_mail(target_id=target_id)
            return {"messages": messages}

        tools_svc.register_tool(
            name="team_member_list",
            handler=team_member_list,
            description="List all members and roles in the team roster.",
            parameters={"type": "object", "properties": {}},
        )

        tools_svc.register_tool(
            name="team_task_create",
            handler=team_task_create,
            description="Create a new task on the team task board.",
            parameters={
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Short task title"},
                    "description": {"type": "string", "description": "Detailed task instructions"},
                    "owner_id": {"type": "string", "description": "Optional assigned member ID"},
                },
                "required": ["subject"],
            },
        )

        tools_svc.register_tool(
            name="team_task_claim",
            handler=team_task_claim,
            description="Claim a task for an agent on the team board.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID e.g. task-1"},
                    "owner_id": {"type": "string", "description": "Member ID of the claimant"},
                },
                "required": ["task_id", "owner_id"],
            },
        )

        tools_svc.register_tool(
            name="team_task_update",
            handler=team_task_update,
            description="Update the status or notes of a task.",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "status": {"type": "string", "description": "New status: pending, in_progress, completed, deleted"},
                    "description": {"type": "string", "description": "Updated notes"},
                },
                "required": ["task_id"],
            },
        )

        tools_svc.register_tool(
            name="team_task_list",
            handler=team_task_list,
            description="List all tasks from the team task board.",
            parameters={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status"},
                },
            },
        )

        tools_svc.register_tool(
            name="team_send_mail",
            handler=team_send_mail,
            description="Send an asynchronous peer message to a teammate's mailbox.",
            parameters={
                "type": "object",
                "properties": {
                    "sender_id": {"type": "string", "description": "Sender agent ID"},
                    "sender_name": {"type": "string", "description": "Sender agent name"},
                    "target_id": {"type": "string", "description": "Target agent ID"},
                    "content": {"type": "string", "description": "Message content"},
                },
                "required": ["sender_id", "sender_name", "target_id", "content"],
            },
        )

        tools_svc.register_tool(
            name="team_read_mail",
            handler=team_read_mail,
            description="Read unread mailbox messages for an agent.",
            parameters={
                "type": "object",
                "properties": {
                    "target_id": {"type": "string", "description": "Agent ID whose mailbox to check"},
                },
                "required": ["target_id"],
            },
        )
