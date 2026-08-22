"""
LLM Domain Handler (`@deepseek-ai/dsh-apiproxy/api/llm`).
Handles `llm.providers`, `llm.models`, `llm.discoverModels`.
Aligned 1:1 with reference `api/llm.ts`.
"""

from typing import Any, Dict


class LLMDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def list_providers(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "providers": [
                {"id": "deepseek", "name": "DeepSeek Official", "baseUrl": "https://api.deepseek.com/v1"},
                {"id": "openai", "name": "OpenAI Compatible", "baseUrl": "https://api.openai.com/v1"},
            ]
        }

    async def list_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        llm = self.ctx.get("llm")
        eff_model = llm.resolve_model() if llm else "deepseek-chat"
        groups = [{
            "id": "deepseek",
            "name": "DeepSeek Official",
            "models": [
                {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)", "description": "High efficiency general reasoning"},
                {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoner)", "description": "Deep reasoning with explicit chain-of-thought"},
            ],
        }]
        return {
            "current": {"provider": "deepseek", "model": eff_model},
            "routable": True,
            "groups": groups,
            "failures": [],
        }

    async def discover_models(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.list_models(payload)
