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
        # TS contract: { refs: string[] } -> { credentials: Record<string, CredentialView> }
        # CredentialView = { configured: boolean, source?: string, writable: boolean }
        refs = payload.get("refs") or payload.get("references") or []
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, list):
            refs = []
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        credentials_svc = self.ctx.get("credentials") if hasattr(self.ctx, "get") else None
        result: Dict[str, Any] = {}
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                continue
            configured = False
            source = None
            writable = True
            # Try credentials service first
            if credentials_svc and hasattr(credentials_svc, "describe"):
                try:
                    desc = credentials_svc.describe(ref)
                    if desc and desc.get("configured"):
                        configured = True
                        source = desc.get("source")
                        writable = desc.get("writable", True)
                except Exception:
                    pass
            # Fallback to env / llm static
            if not configured:
                env_val = os.environ.get(ref) or os.environ.get(ref.upper())
                if env_val:
                    configured = True
                    source = "env"
                elif llm and getattr(llm, "static_api_key", None) and ref in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", llm.api_key_env):
                    configured = True
                    source = "file"
            # Check env shadowing -> not writable
            if os.environ.get(ref):
                writable = False
            elif ref in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY") and (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")):
                # env shadows file
                if configured and source != "env":
                    writable = False
            result[ref] = {"configured": configured, "writable": writable}
            if source:
                result[ref]["source"] = source
        if not refs:
            has_key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or (llm and getattr(llm, "static_api_key", None)))
            result = {
                "DEEPSEEK_API_KEY": {"configured": has_key, "source": "env" if os.environ.get("DEEPSEEK_API_KEY") else ("file" if has_key else None), "writable": not bool(os.environ.get("DEEPSEEK_API_KEY"))},
                "OPENAI_API_KEY": {"configured": bool(os.environ.get("OPENAI_API_KEY")), "source": "env" if os.environ.get("OPENAI_API_KEY") else None, "writable": not bool(os.environ.get("OPENAI_API_KEY"))},
            }
            for k, v in list(result.items()):
                if v.get("source") is None:
                    v.pop("source", None)
            return result
        return result

    async def set_credentials(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # TS: { ref: string, value: string }
        ref = payload.get("ref") or payload.get("provider") or payload.get("credentialId") or "DEEPSEEK_API_KEY"
        value = payload.get("value") or payload.get("apiKey") or payload.get("api_key") or ""
        # Shadowing check
        if os.environ.get(ref):
            raise ValueError(f"credential-rejected: ref '{ref}' is shadowed by environment")
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        credentials_svc = self.ctx.get("credentials") if hasattr(self.ctx, "get") else None
        if credentials_svc and hasattr(credentials_svc, "set"):
            try:
                credentials_svc.set(ref, value)
            except Exception as e:
                raise ValueError(f"credential-rejected: {e}")
        elif llm and value:
            llm.static_api_key = value
            # Also persist via settings/credentials file if available
            if credentials_svc and hasattr(credentials_svc, "_credentials"):
                try:
                    credentials_svc._credentials[ref] = value
                except Exception:
                    pass
        return {}

    async def unset_credentials(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ref = payload.get("ref") or payload.get("provider") or "DEEPSEEK_API_KEY"
        if os.environ.get(ref):
            raise ValueError(f"credential-rejected: ref '{ref}' is shadowed by environment")
        llm = self.ctx.get("llm") if hasattr(self.ctx, "get") else None
        credentials_svc = self.ctx.get("credentials") if hasattr(self.ctx, "get") else None
        if credentials_svc and hasattr(credentials_svc, "unset"):
            try:
                credentials_svc.unset(ref)
            except Exception:
                pass
        elif llm:
            llm.static_api_key = None
        return {}
