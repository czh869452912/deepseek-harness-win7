import asyncio
import copy
import time
import uuid
from typing import Any, Dict, List, Optional
from dsh.cordis.context import Context


class SubagentRecord:
    def __init__(
        self,
        subagent_id: str,
        parent_session_id: str,
        task: str,
        provider: str = "spawn",
        depth: int = 1,
        continuable: bool = False,
    ):
        self.id = subagent_id
        self.parent_session_id = parent_session_id
        self.task = task
        self.provider = provider
        self.depth = depth
        self.continuable = continuable
        self.status = "running"
        self.result: Optional[str] = None
        self.started_at = int(time.time() * 1000)
        self.finished_at: Optional[int] = None
        self.inbox: List[Dict[str, Any]] = []
        self._completion_event = asyncio.Event()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "parentSessionId": self.parent_session_id,
            "task": self.task,
            "provider": self.provider,
            "depth": self.depth,
            "status": self.status,
            "continuable": self.continuable,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "result": self.result,
        }

    def complete(self, result: str) -> None:
        self.status = "completed"
        self.result = result
        self.finished_at = int(time.time() * 1000)
        self._completion_event.set()

    def interrupt(self) -> None:
        self.status = "interrupted"
        self.finished_at = int(time.time() * 1000)
        self._completion_event.set()

    def queue_message(self, message: str, sender_id: Optional[str] = None) -> str:
        msg_id = f"msg-{uuid.uuid4().hex[:8]}"
        self.inbox.append({
            "messageId": msg_id,
            "senderId": sender_id,
            "content": message,
            "timestamp": int(time.time() * 1000),
        })
        return msg_id


class SubagentRegistry:
    """
    Subagents registry mounted at ctx.subagents.
    Provides spawn, fork with session cloning, continuable background delegation, and followups.
    """

    def __init__(self, ctx: Optional[Any] = None, max_depth: int = 3):
        self.ctx = ctx
        self.max_depth = max_depth
        self._subagents: Dict[str, SubagentRecord] = {}

    def spawn(
        self,
        parent_session_id: str,
        task: str,
        provider: str = "spawn",
        depth: int = 1,
        continuable: bool = False,
    ) -> SubagentRecord:
        if depth > self.max_depth:
            raise RuntimeError(f"Subagent max depth exceeded ({depth} > {self.max_depth})")

        subagent_id = f"subagent-{uuid.uuid4().hex[:8]}"
        record = SubagentRecord(
            subagent_id=subagent_id,
            parent_session_id=parent_session_id,
            task=task,
            provider=provider,
            depth=depth,
            continuable=continuable,
        )
        self._subagents[subagent_id] = record
        return record

    def fork(
        self,
        parent_session_id: str,
        task: str,
        depth: int = 1,
    ) -> SubagentRecord:
        if depth > self.max_depth:
            raise RuntimeError(f"Subagent max depth exceeded ({depth} > {self.max_depth})")

        # Session history cloning
        if self.ctx and self.ctx.has("sessions"):
            sessions_svc = self.ctx.get("sessions")
            parent_sess = sessions_svc.get(parent_session_id) if hasattr(sessions_svc, "get") else None
            if parent_sess:
                forked_sess_id = f"sess-fork-{uuid.uuid4().hex[:8]}"
                forked_sess = sessions_svc.create(forked_sess_id) if hasattr(sessions_svc, "create") else None
                if forked_sess and hasattr(parent_sess, "events"):
                    forked_sess.events = copy.deepcopy(parent_sess.events)

        record = self.spawn(parent_session_id=parent_session_id, task=task, provider="fork", depth=depth)
        return record

    def start_continuable(
        self,
        parent_session_id: str,
        task: str,
        provider: str = "spawn",
    ) -> Dict[str, Any]:
        record = self.spawn(parent_session_id=parent_session_id, task=task, provider=provider, continuable=True)
        return {"childId": record.id}

    def followup(
        self,
        subagent_id: str,
        message: str,
        sender_session_id: Optional[str] = None,
    ) -> str:
        rec = self._subagents.get(subagent_id)
        if not rec:
            raise ValueError(f"No subagent found with ID '{subagent_id}'")
        msg_id = rec.queue_message(message, sender_id=sender_session_id)
        if self.ctx:
            self.ctx.emit("subagent/message-queued", {
                "subagentId": subagent_id,
                "messageId": msg_id,
                "message": message,
            })
        return msg_id

    def interrupt(self, subagent_id: str, authority: Optional[Any] = None) -> bool:
        rec = self._subagents.get(subagent_id)
        if rec and rec.status == "running":
            rec.interrupt()
            if self.ctx:
                self.ctx.emit("subagent/interrupted", {"subagentId": subagent_id})
            return True
        return False

    def get(self, subagent_id: str) -> Optional[SubagentRecord]:
        return self._subagents.get(subagent_id)

    def list_children(self, parent_session_id: Optional[str] = None) -> List[SubagentRecord]:
        if parent_session_id is None:
            return list(self._subagents.values())
        return [s for s in self._subagents.values() if s.parent_session_id == parent_session_id]

