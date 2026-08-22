"""
Goals Domain Handler (`@deepseek-ai/dsh-apiproxy/api/goals`).
Handles `goal.create`, `goal.edit`, `goal.pause`, `goal.resume`, `goal.complete`, `goal.clear`.
Aligned 1:1 with reference `api/goals.ts`.
"""

from typing import Any, Dict


class GoalsDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def create_goal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        goals = self.ctx.get("goals")
        obj = payload.get("objective", "New Goal")
        g = goals.create_goal(objective=obj) if goals else None
        ref = {"id": g.id, "revision": g.revision} if g else {"id": "g-0", "revision": 0}
        return {"ref": ref, "goal": g.to_dict() if g else None}

    async def edit_goal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        goals = self.ctx.get("goals")
        g = goals.get_goal() if goals else None
        return {"ref": {"id": g.id, "revision": g.revision} if g else {"id": "g-0", "revision": 0}}

    async def pause_goal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        goals = self.ctx.get("goals")
        g = goals.get_goal() if goals else None
        if goals and g:
            g = goals.update_goal(g.id, g.revision, "pause")
        return {"ref": {"id": g.id, "revision": g.revision} if g else {"id": "g-0", "revision": 0}}

    async def resume_goal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        goals = self.ctx.get("goals")
        g = goals.get_goal() if goals else None
        if goals and g:
            g = goals.update_goal(g.id, g.revision, "resume")
        return {"ref": {"id": g.id, "revision": g.revision} if g else {"id": "g-0", "revision": 0}}

    async def complete_goal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        goals = self.ctx.get("goals")
        g = goals.get_goal() if goals else None
        if goals and g:
            g = goals.update_goal(g.id, g.revision, "complete")
        return {"ref": {"id": g.id, "revision": g.revision} if g else {"id": "g-0", "revision": 0}}

    async def clear_goal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        goals = self.ctx.get("goals")
        if goals:
            goals.clear_goal()
        return {"cleared": True}
