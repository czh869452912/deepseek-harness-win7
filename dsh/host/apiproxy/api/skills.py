"""
Skills Domain Handler (`@deepseek-ai/dsh-apiproxy/api/skills`).
Handles `skill.list`. Aligned 1:1 with reference `api/skills.ts`.
"""

from typing import Any, Dict


class SkillsDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def list_skills(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        skills_svc = self.ctx.get("skills")
        items = await skills_svc.list({"cwd": payload.get("cwd")}) if skills_svc is not None else []
        return {"skills": items, "items": items}
