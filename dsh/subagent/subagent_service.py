import asyncio
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
    ):
        self.id = subagent_id
        self.parent_session_id = parent_session_id
        self.task = task
        self.provider = provider
        self.depth = depth
        self.status = "running"
        self.result: Optional[str] = None
        self.started_at = int(time.time() * 1000)
        self.finished_at: Optional[int] = None
        self._completion_event = asyncio.Event()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "parentSessionId": self.parent_session_id,
            "task": self.task,
            "provider": self.provider,
            "depth": self.depth,
            "status": self.status,
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


class SubagentRegistry:
    """
    Subagents registry mounted at ctx.subagents.
    """

    def __init__(self, ctx: Optional[Any] = None, max_depth: int = 3):
        self.ctx = ctx
        self.max_depth = max_depth
        self._subagents: Dict[str, SubagentRecord] = {}

    def spawn(self, parent_session_id: str, task: str, provider: str = "spawn", depth: int = 1) -> SubagentRecord:
        if depth > self.max_depth:
            raise RuntimeError(f"Subagent max depth exceeded ({depth} > {self.max_depth})")

        subagent_id = f"subagent-{uuid.uuid4().hex[:8]}"
        record = SubagentRecord(
            subagent_id=subagent_id,
            parent_session_id=parent_session_id,
            task=task,
            provider=provider,
            depth=depth,
        )
        self._subagents[subagent_id] = record
        return record

    def get(self, subagent_id: str) -> Optional[SubagentRecord]:
        return self._subagents.get(subagent_id)

    def list_children(self, parent_session_id: Optional[str] = None) -> List[SubagentRecord]:
        if parent_session_id is None:
            return list(self._subagents.values())
        return [s for s in self._subagents.values() if s.parent_session_id == parent_session_id]

    def interrupt(self, subagent_id: str) -> bool:
        rec = self._subagents.get(subagent_id)
        if rec and rec.status == "running":
            rec.interrupt()
            return True
        return False
