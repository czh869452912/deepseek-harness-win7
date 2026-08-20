import json
import os
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


class CredentialsService:
    """
    Credentials Service registered at `ctx.credentials`.
    Manages resolution of sensitive credentials (API keys).
    Resolution Order:
    1. Runtime stored credentials
    2. User home credentials store (~/.dsh/credentials.json)
    3. Environment variables (DEEPSEEK_API_KEY, OPENAI_API_KEY, etc.)
    """

    def __init__(self, ctx: Optional[Any] = None, credentials_file: Optional[str] = None):
        self.ctx = ctx
        self._credentials: Dict[str, str] = {}

        if credentials_file:
            self.filepath = os.path.abspath(credentials_file)
        else:
            home = os.path.expanduser("~")
            self.filepath = os.path.join(home, ".dsh", "credentials.json")

        self.load()

    def load(self) -> None:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, str):
                                self._credentials[k] = v
            except Exception as e:
                print(f"[CredentialsService Warning] Failed to load credentials from {self.filepath}: {e}")

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self._credentials, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CredentialsService Error] Failed to save credentials to {self.filepath}: {e}")

    def set_credential(self, ref_name: str, value: str, save_to_disk: bool = True) -> None:
        self._credentials[ref_name] = value
        if save_to_disk:
            self.save()

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
        credentials_file = self.config.get("credentialsFile")
        creds_service = CredentialsService(ctx=ctx, credentials_file=credentials_file)

        initial_creds = self.config.get("credentials", {})
        for ref_name, val in initial_creds.items():
            creds_service.set_credential(ref_name, val, save_to_disk=False)

        ctx.set_service("credentials", creds_service)
