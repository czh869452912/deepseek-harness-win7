"""
Agent Teams durable types and view models matching reference/packages/experimental/agent-team/src/types.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List, Optional


class TeamMemberPhase:
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FAILED = "failed"


class TeamMemberStatus:
    RUNNING = "running"
    IDLE = "idle"
    INACTIVE = "inactive"
    PROVISIONING = "provisioning"
    FAILED = "failed"


class TeamTaskStatus:
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELETED = "deleted"


class TeamMemberSnapshot:
    """Durable record of a teammate's metadata."""
    def __init__(
        self,
        member_id: str,
        name: str,
        description: str = "",
        provider: str = "subagent",
        context_mode: str = "fresh",
        phase: str = TeamMemberPhase.ACTIVE,
        error: Optional[str] = None,
        role: str = "teammate",
        model: Optional[str] = None,
    ):
        self.id = member_id
        self.name = name
        self.description = description
        self.provider = provider
        self.context = context_mode
        self.phase = phase
        self.error = error
        self.role = role
        self.model = model

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "context": self.context,
            "phase": self.phase,
            "role": self.role,
            "model": self.model,
            "error": self.error,
        }


class TeamTaskSnapshot:
    """Durable snapshot of a shared task on the Team Task Board."""
    def __init__(
        self,
        task_id: str,
        subject: str,
        description: str = "",
        status: str = TeamTaskStatus.PENDING,
        owner_id: Optional[str] = None,
        blocked_by: Optional[List[str]] = None,
        write_scopes: Optional[List[str]] = None,
        revision: int = 1,
    ):
        self.id = task_id
        self.subject = subject
        self.description = description
        self.status = status
        self.owner_id = owner_id
        self.blocked_by = blocked_by or []
        self.write_scopes = write_scopes or []
        self.revision = revision

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "ownerId": self.owner_id,
            "blockedBy": self.blocked_by,
            "writeScopes": self.write_scopes,
            "revision": self.revision,
        }


class TeamMessageSnapshot:
    """Durable peer mailbox message."""
    def __init__(
        self,
        message_id: str,
        sender_id: str,
        sender_name: str,
        target_id: str,
        content: str,
        delivery: str = "wakeup",
        read: bool = False,
    ):
        self.id = message_id
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.target_id = target_id
        self.content = content
        self.delivery = delivery
        self.read = read

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "senderId": self.sender_id,
            "senderName": self.sender_name,
            "targetId": self.target_id,
            "content": self.content,
            "delivery": self.delivery,
            "read": self.read,
        }
