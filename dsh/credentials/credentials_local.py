import json
import os
from typing import Any, Dict, Optional
import yaml

from dsh.cordis.environment import resolve_dsh_home, LaunchEnvironmentSnapshot
from dsh.cordis.plugin import Plugin


class CredentialsService:
    """
    Credentials Service registered at `ctx.credentials`.
    Manages resolution and persistence of sensitive credentials (API keys).

    Resolution Order (matches DeepSeek Harness spec):
    1. Inherited process environment (os.environ, read-only override)
    2. User home managed credentials file ($DSH_HOME/.credentials.yaml or credentials.json)
    3. Discovered .env fallbacks (<cwd>/.env, $DSH_HOME/.env)
    """

    def __init__(self, ctx: Optional[Any] = None, credentials_file: Optional[str] = None):
        self.ctx = ctx
        self._credentials: Dict[str, str] = {}
        self._format: str = "yaml"

        if credentials_file:
            self.filepath = os.path.abspath(credentials_file)
        else:
            home_dir = resolve_dsh_home()
            yaml_path = os.path.join(home_dir, ".credentials.yaml")
            json_path = os.path.join(home_dir, "credentials.json")
            if os.path.exists(yaml_path):
                self.filepath = yaml_path
            elif os.path.exists(json_path):
                self.filepath = json_path
            else:
                self.filepath = yaml_path

        if self.filepath.endswith(".json"):
            self._format = "json"
        else:
            self._format = "yaml"

        self.load()

    def load(self) -> None:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                if self._format == "json":
                    data = json.loads(content) if content.strip() else {}
                else:
                    data = yaml.safe_load(content) or {}

                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, str):
                            self._credentials[k] = v
            except Exception as e:
                if self.ctx and hasattr(self.ctx, "logger") and self.ctx.logger:
                    self.ctx.logger.warn("Failed to load credentials from %s: %s", self.filepath, str(e))
                else:
                    print(f"[CredentialsService Warning] Failed to load credentials from {self.filepath}: {e}")

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                if self._format == "json":
                    json.dump(self._credentials, f, indent=2, ensure_ascii=False)
                else:
                    yaml.dump(self._credentials, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            if self.ctx and hasattr(self.ctx, "logger") and self.ctx.logger:
                self.ctx.logger.error("Failed to save credentials to %s: %s", self.filepath, str(e))
            else:
                print(f"[CredentialsService Error] Failed to save credentials to {self.filepath}: {e}")

    def set_credential(self, ref_name: str, value: str, save_to_disk: bool = True) -> None:
        # Check if shadowed by launch environment
        if ref_name in os.environ:
            raise ValueError(
                f"credentials-local: '{ref_name}' is supplied read-only by the launching environment, "
                "so setting it would be shadowed; unset it in the shell instead."
            )
        self._credentials[ref_name] = value
        if save_to_disk:
            self.save()

    def resolve(self, ref_name: str) -> Optional[str]:
        # 1. Inherited process environment (wins)
        if ref_name in os.environ and os.environ[ref_name]:
            return os.environ[ref_name]

        # 2. Managed on-disk credentials file
        if ref_name in self._credentials and self._credentials[ref_name]:
            return self._credentials[ref_name]

        # 3. Discovered .env fallback layers
        if self.ctx and self.ctx.has("launch_environment"):
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = launch_env.get_from(ref_name, ["project-env", "user-env"])
            if entry and entry.value:
                return entry.value

        return None

    def describe(self, ref_name: str) -> Dict[str, Any]:
        """Describe whether a credential is configured, its source, and if writable."""
        if ref_name in os.environ and os.environ[ref_name]:
            return {"configured": True, "source": "env", "writable": False}
        if ref_name in self._credentials and self._credentials[ref_name]:
            return {"configured": True, "source": "file", "writable": True}
        if self.ctx and self.ctx.has("launch_environment"):
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = launch_env.get_from(ref_name, ["project-env", "user-env"])
            if entry and entry.value:
                return {"configured": True, "source": entry.source, "writable": True}
        return {"configured": False, "source": None, "writable": True}


class CredentialsLocalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-credentials-local`: Mounts local credentials management service (`ctx.credentials`).
    """

    id = "credentials-local"
    name = "@deepseek-ai/dsh-credentials-local"

    def apply(self, ctx: Any) -> None:
        cfg = self.config or {}
        credentials_file = cfg.get("credentialsFile", cfg.get("path"))
        creds_service = CredentialsService(ctx=ctx, credentials_file=credentials_file)

        initial_creds = cfg.get("credentials", {})
        for ref_name, val in initial_creds.items():
            creds_service._credentials[ref_name] = str(val)

        ctx.set_service("credentials", creds_service)
