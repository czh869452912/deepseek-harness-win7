import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional
from dsh.cordis.context import Context


class JobSnapshot:
    def __init__(
        self,
        job_id: str,
        kind: str,
        label: str,
        owner_session_id: str,
        status: str = "running",
        detail: Optional[str] = None,
    ):
        self.id = job_id
        self.kind = kind
        self.label = label
        self.owner_session_id = owner_session_id
        self.status = status
        self.detail = detail
        self.started_at = int(time.time() * 1000)
        self.finished_at: Optional[int] = None
        self.output_buffer: List[str] = []
        self._completion_event = asyncio.Event()

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "startedAt": self.started_at,
        }
        if self.detail is not None:
            data["detail"] = self.detail
        if self.finished_at is not None:
            data["finishedAt"] = self.finished_at
        return data

    def append_output(self, text: str) -> None:
        self.output_buffer.append(text)

    def mark_finished(self, status: str = "completed", detail: Optional[str] = None) -> None:
        self.status = status
        self.finished_at = int(time.time() * 1000)
        if detail:
            self.detail = detail
        self._completion_event.set()


class JobsService:
    """
    Jobs Service mounted on ctx.jobs / ctx.tasks.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx
        self._jobs: Dict[str, JobSnapshot] = {}

    def create_job(
        self,
        kind: str,
        label: str,
        owner_session_id: str,
        detail: Optional[str] = None,
    ) -> JobSnapshot:
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        job = JobSnapshot(
            job_id=job_id,
            kind=kind,
            label=label,
            owner_session_id=owner_session_id,
            detail=detail,
        )
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[JobSnapshot]:
        return self._jobs.get(job_id)

    def list_jobs(self, owner_session_id: Optional[str] = None) -> List[JobSnapshot]:
        if owner_session_id is None:
            return list(self._jobs.values())
        return [j for j in self._jobs.values() if j.owner_session_id == owner_session_id]

    def kill_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status not in ("running", "stopping"):
            return False
        job.mark_finished(status="killed", detail="Killed by user/agent request")
        return True
