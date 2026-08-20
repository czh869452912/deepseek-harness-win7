import os
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


class CredentialsService:
    """
    Credentials Service registered at `ctx.credentials`.
    Manages resolution of sensitive credentials (API keys).
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx
        self._credentials: Dict[str, str] = {}

    def set_credential(self, ref_name: str, value: str) -> None:
        self._credentials[ref_name] = value

    def resolve(self, ref_name: str) -> Optional[str]:
        if ref_name in self._credentials and self._credentials[ref_name]:
            return self._credentials[ref_name]

        env_val = os.environ.get(ref_name)
        if env_val:
            return env_val

        return None


class CredentialsLocalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-credentials-local`: Mounts local credentials management service (`ctx.credentials`).
    """

    id = "credentials-local"
    name = "@deepseek-ai/dsh-credentials-local"

    def apply(self, ctx: Any) -> None:
        creds_service = CredentialsService(ctx=ctx)

        initial_creds = self.config.get("credentials", {})
        for ref_name, val in initial_creds.items():
            creds_service.set_credential(ref_name, val)

        ctx.set_service("credentials", creds_service)
