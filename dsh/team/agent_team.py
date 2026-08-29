"""
Agent Teams service matching @deepseek-ai/dsh-agent-team.
Manages team membership roster, shared task board DAG, and asynchronous mailbox delivery.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.team.types import (
    TeamMemberPhase,
    TeamMemberSnapshot,
    TeamMessageSnapshot,
    TeamTaskSnapshot,
    TeamTaskStatus,
)


class TeamService(Service):
    """
    Agent Teams service mounted on ctx.agentTeams.
    Coordinates multiple agents across durable roster, taskboard, and mailbox.
    """

    name = "agentTeams"

    def __init__(self, ctx: Any):
        super().__init__(ctx, name="agentTeams")
        self._members: Dict[str, TeamMemberSnapshot] = {}
        self._tasks: Dict[str, TeamTaskSnapshot] = {}
        self._mailbox: List[TeamMessageSnapshot] = []
        self._task_counter: int = 0

    # --- Roster & Membership ---
    def register_member(
        self,
        name: str,
        description: str = "",
        member_id: Optional[str] = None,
        provider: str = "subagent",
        role: str = "teammate",
        model: Optional[str] = None,
    ) -> TeamMemberSnapshot:
        mid = member_id or f"member-{uuid.uuid4().hex[:8]}"
        member = TeamMemberSnapshot(
            member_id=mid,
            name=name,
            description=description,
            provider=provider,
            phase=TeamMemberPhase.ACTIVE,
            role=role,
            model=model,
        )
        self._members[mid] = member
        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("team/member-joined", member.to_dict())
        return member

    def list_members(self) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self._members.values()]

    def get_member(self, member_id: str) -> Optional[Dict[str, Any]]:
        m = self._members.get(member_id)
        return m.to_dict() if m else None

    # --- Task Board DAG ---
    def create_task(
        self,
        subject: str,
        description: str = "",
        owner_id: Optional[str] = None,
        blocked_by: Optional[List[str]] = None,
        write_scopes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        self._task_counter += 1
        tid = f"task-{self._task_counter}"
        status = TeamTaskStatus.IN_PROGRESS if owner_id else TeamTaskStatus.PENDING
        task = TeamTaskSnapshot(
            task_id=tid,
            subject=subject,
            description=description,
            status=status,
            owner_id=owner_id,
            blocked_by=blocked_by or [],
            write_scopes=write_scopes or [],
            revision=1,
        )
        self._tasks[tid] = task
        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("team/task-created", task.to_dict())
        return task.to_dict()

    def claim_task(self, task_id: str, owner_id: str) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found")
        task.owner_id = owner_id
        task.status = TeamTaskStatus.IN_PROGRESS
        task.revision += 1
        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("team/task-updated", task.to_dict())
        return task.to_dict()

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        description: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found")
        if status:
            task.status = status
        if description is not None:
            task.description = description
        if owner_id is not None:
            task.owner_id = owner_id
        task.revision += 1
        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("team/task-updated", task.to_dict())
        return task.to_dict()

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return [t.to_dict() for t in tasks]

    # --- Mailbox ---
    def send_mail(
        self,
        sender_id: str,
        sender_name: str,
        target_id: str,
        content: str,
        delivery: str = "wakeup",
    ) -> Dict[str, Any]:
        msg_id = f"msg-{uuid.uuid4().hex[:8]}"
        msg = TeamMessageSnapshot(
            message_id=msg_id,
            sender_id=sender_id,
            sender_name=sender_name,
            target_id=target_id,
            content=content,
            delivery=delivery,
            read=False,
        )
        self._mailbox.append(msg)
        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("team/mail-sent", msg.to_dict())
        return msg.to_dict()

    def read_mail(self, target_id: str, mark_as_read: bool = True) -> List[Dict[str, Any]]:
        result = []
        for msg in self._mailbox:
            if msg.target_id == target_id:
                result.append(msg.to_dict())
                if mark_as_read:
                    msg.read = True
        return result


class AgentTeamPlugin(Plugin):
    """Mounts the Agent Teams service."""
    name = "agent-team"
    id = "@deepseek-ai/dsh-agent-team"

    def apply(self, ctx: Any) -> None:
        TeamService(ctx)
