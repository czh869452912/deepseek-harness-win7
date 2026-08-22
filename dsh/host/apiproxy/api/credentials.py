"""
Credentials Domain Handler (`@deepseek-ai/dsh-apiproxy/api/credentials`).
Handles `credentials.describe`, `credentials.set`, `credentials.unset`.
Aligned 1:1 with reference `api/credentials.ts`.
"""

import os
from typing import Any, Dict


class CredentialsDomainHandler:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def describe_credentials(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        llm = self.ctx.get("llm")
        has_key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or (llm and getattr(llm, "static_api_key", None)))
        return {
            "providers": [
                {"id": "deepseek", "name": "DeepSeek API", "configured": has_key},
                {"id": "openai", "name": "OpenAI API", "configured": bool(os.environ.get("OPENAI_API_KEY"))},
            ]
        }

    async def set_credentials(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider = payload.get("provider", "deepseek")
        api_key = payload.get("apiKey", "")
        llm = self.ctx.get("llm")
        if llm and api_key:
            llm.static_api_key = api_key
        return {"success": True, "provider": provider}

    async def unset_credentials(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        provider = payload.get("provider", "deepseek")
        llm = self.ctx.get("llm")
        if llm:
            llm.static_api_key = None
        return {"unset": True, "provider": provider}
