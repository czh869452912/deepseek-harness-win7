"""
Subagents Domain Handler (`@deepseek-ai/dsh-apiproxy/api/subagents`).
Handles `subagent.list`, `subagent.history`, `subagent.prompt`, `subagent.interrupt`.
Aligned 1:1 with reference `api/subagents.ts`.
"""

from typing import Any, Dict


class SubagentsDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def list_subagents(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        subagents_svc = self.ctx.get("subagents")
        items = subagents_svc.list_subagents() if subagents_svc and hasattr(subagents_svc, "list_subagents") else []
        return {"subagents": items, "items": items}

    async def get_history(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sub_id = payload.get("subagentId")
        subagents_svc = self.ctx.get("subagents")
        history = subagents_svc.get_history(sub_id) if subagents_svc and hasattr(subagents_svc, "get_history") else []
        return {"subagentId": sub_id, "history": history}

    async def prompt_subagent(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sub_id = payload.get("subagentId")
        prompt_text = payload.get("prompt", "")
        subagents_svc = self.ctx.get("subagents")
        res = await subagents_svc.prompt(sub_id, prompt_text) if subagents_svc and hasattr(subagents_svc, "prompt") else {"accepted": True}
        return res

    async def interrupt_subagent(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sub_id = payload.get("subagentId")
        subagents_svc = self.ctx.get("subagents")
        if subagents_svc and hasattr(subagents_svc, "interrupt"):
            subagents_svc.interrupt(sub_id)
        return {"interrupted": True, "subagentId": sub_id}
