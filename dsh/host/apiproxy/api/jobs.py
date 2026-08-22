"""
Jobs Domain Handler (`@deepseek-ai/dsh-apiproxy/api/jobs`).
Handles `jobs.list`.
Aligned 1:1 with reference `api/jobs.ts`.
"""

from typing import Any, Dict


class JobsDomainHandler:
    def __init__(self, ctx: Any, background_jobs: Dict[str, Any]):
        self.ctx = ctx
        self._background_jobs = background_jobs

    async def list_jobs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload.get("sessionId", "default-session")
        jobs = self._background_jobs.get(sid, [])
        return {"jobs": jobs, "items": jobs}
