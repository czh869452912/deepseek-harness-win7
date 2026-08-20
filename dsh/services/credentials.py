import os
from typing import Any, Dict, Optional


class CredentialsService:
    """
    Credentials Service registered at `ctx.credentials`.
    Manages resolution of sensitive credentials (API keys).
    Resolution Order:
    1. Runtime stored credentials (e.g. set via Web UI or CLI)
    2. Environment variables (DEEPSEEK_API_KEY, OPENAI_API_KEY, etc.)
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx
        self._credentials: Dict[str, str] = {}

    def set_credential(self, ref_name: str, value: str) -> None:
        """
        Store a credential under reference name (e.g. 'DEEPSEEK_API_KEY').
        """
        self._credentials[ref_name] = value

    def resolve(self, ref_name: str) -> Optional[str]:
        """
        Resolve credential value by reference name.
        """
        if ref_name in self._credentials and self._credentials[ref_name]:
            return self._credentials[ref_name]

        # Environment variable fallback
        env_val = os.environ.get(ref_name)
        if env_val:
            return env_val

        return None
