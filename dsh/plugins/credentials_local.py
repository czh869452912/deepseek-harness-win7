from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.services.credentials import CredentialsService


class CredentialsLocalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-credentials-local`: Mounts local credentials management service (`ctx.credentials`).
    """

    id = "credentials-local"
    name = "@deepseek-ai/dsh-credentials-local"

    def apply(self, ctx: Any) -> None:
        creds_service = CredentialsService(ctx=ctx)

        # Pre-seed initial credentials from plugin config if present
        initial_creds = self.config.get("credentials", {})
        for ref_name, val in initial_creds.items():
            creds_service.set_credential(ref_name, val)

        ctx.set_service("credentials", creds_service)
