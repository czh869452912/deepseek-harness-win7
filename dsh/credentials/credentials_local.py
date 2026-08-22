import json
import os
import re
from typing import Any, Dict, Optional
import yaml

from dsh.cordis.environment import resolve_dsh_home, LaunchEnvironmentSnapshot
from dsh.cordis.plugin import Plugin

# 1:1 with reference packages/credentials/credentials-local/src/index.ts
CREDENTIALS_FILENAME = ".credentials.yaml"
DOCUMENT_VERSION = 1

# 1:1 with reference packages/credentials/credentials/src/index.ts REF_PATTERN
REF_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_credential_ref_name(value: str) -> bool:
    """Whether a raw string could name a credential reference at all."""
    return bool(REF_PATTERN.match(value))


class CredentialsService:
    """
    Credentials Service registered at `ctx.credentials`.
    Manages resolution and persistence of sensitive credentials (API keys).

    Resolution Order (1:1 with TS credentials-local, most trusted first):
    1. Inherited process environment (os.environ, read-only, wins)
    2. Provider-managed `$DSH_HOME/.credentials.yaml` (writable store)
    3. `<invocation cwd>/.env` (read-only fallback)
    4. `$DSH_HOME/.env` (read-only fallback)
    """

    def __init__(self, ctx: Optional[Any] = None, credentials_file: Optional[str] = None):
        self.ctx = ctx
        self._credentials: Dict[str, str] = {}
        self._records: Dict[str, Any] = {}
        self._format: str = "yaml"

        if credentials_file:
            self.filepath = os.path.abspath(credentials_file)
        else:
            home_dir = resolve_dsh_home()
            yaml_path = os.path.join(home_dir, CREDENTIALS_FILENAME)
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

    def _log(self, level: str, message: str) -> None:
        logger = getattr(self.ctx, "logger", None) if self.ctx else None
        if logger is not None:
            try:
                getattr(logger, level)(message)
                return
            except Exception:
                pass
        print("[CredentialsService {}] {}".format(level.capitalize(), message))

    def load(self) -> None:
        """
        Boot read (1:1 with TS loadInitial): an absent file is an empty store;
        an invalid one fails loud, because a credentials document that exists
        but cannot be trusted must never be treated as "no credentials stored".
        The one exception is the recognized pre-release flat layout, which is
        upgraded in place first.
        """
        if not os.path.exists(self.filepath):
            return
        with open(self.filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if self._format == "json":
            # Legacy Python port layout: a flat JSON object of ref -> value.
            data = json.loads(content) if content.strip() else {}
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str):
                        self._credentials[k] = v
            return
        self._load_yaml(content)

    def _load_yaml(self, content: str) -> None:
        try:
            data = yaml.safe_load(content)
        except Exception as e:
            raise ValueError(
                "credentials-local: invalid document at {}: {}".format(self.filepath, e)
            )
        if data is None:
            data = {}
        if not isinstance(data, dict) or isinstance(data, list):
            raise TypeError("credentials-local: {} must be a mapping".format(self.filepath))
        if len(data) == 0:
            return
        if "version" not in data:
            # Recognized pre-release flat layout: migrate in place (values verbatim).
            if self._is_flat_layout(data):
                self._credentials = dict(data)
                self.save()
                self._log(
                    "info",
                    "credentials-local: migrated {} to the version {} layout; values are unchanged".format(
                        self.filepath, DOCUMENT_VERSION
                    ),
                )
                return
            keys = list(data.keys())
            raise ValueError(
                "credentials-local: {} uses the pre-release flat layout. Add `version: {}`".format(
                    self.filepath, DOCUMENT_VERSION
                )
                + " and nest the existing {} {} under `refs:`.".format(
                    len(keys), "entry" if len(keys) == 1 else "entries"
                )
                + " No values need to change."
            )
        if data["version"] != DOCUMENT_VERSION:
            raise ValueError(
                "credentials-local: {} declares version {}; this build reads version {}".format(
                    self.filepath, json.dumps(data["version"]), DOCUMENT_VERSION
                )
            )
        for key in data.keys():
            if key not in ("version", "refs", "records"):
                raise ValueError(
                    'credentials-local: unknown top-level key "{}" in {}'.format(key, self.filepath)
                )
        refs = data.get("refs") or {}
        if not isinstance(refs, dict):
            raise TypeError('credentials-local: "refs" in {} must be a mapping'.format(self.filepath))
        for k, v in refs.items():
            if not isinstance(v, str):
                raise TypeError(
                    'credentials-local: the value for "{}" in {} must be a string'.format(k, self.filepath)
                )
            if len(v) == 0:
                raise ValueError(
                    'credentials-local: the value for "{}" in {} is empty; remove the key instead'.format(
                        k, self.filepath
                    )
                )
            self._credentials[k] = v
        records = data.get("records") or {}
        if isinstance(records, dict):
            self._records = dict(records)

    def _is_flat_layout(self, data: Dict[str, Any]) -> bool:
        """The recognized flat layout: addressable ref names over non-empty string values."""
        for k, v in data.items():
            if not isinstance(k, str) or not is_credential_ref_name(k) or k == "version":
                return False
            if not isinstance(v, str) or len(v) == 0:
                return False
        return True

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        if self._format == "json":
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self._credentials, f, indent=2, ensure_ascii=False)
            return
        # Versioned YAML document (1:1 with the TS version-1 layout).
        document: Dict[str, Any] = {"version": DOCUMENT_VERSION, "refs": dict(self._credentials)}
        if self._records:
            document["records"] = dict(self._records)
        with open(self.filepath, "w", encoding="utf-8") as f:
            yaml.dump(document, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _assert_unshadowed(self, ref_name: str, verb: str) -> None:
        """Reject a write the inherited environment would shadow into apparent no-effect."""
        if ref_name in os.environ and os.environ[ref_name]:
            raise ValueError(
                'credentials-local: "{}" is supplied read-only by the launching environment, so {} would be'.format(
                    ref_name, verb
                )
                + " shadowed; unset it in the shell you start dsh from instead"
            )

    def set(self, ref_name: str, value: str) -> None:
        """
        TS seam write path (`CredentialProvider.set`): durably store one value
        in the provider-managed writable source. This is the method the Web
        Models page reaches through the `credentials.set` RPC.
        """
        if not isinstance(value, str) or len(value) == 0:
            raise ValueError(
                'credentials-local: an empty value cannot be stored for "{}"; use unset'.format(ref_name)
            )
        self._assert_unshadowed(ref_name, "set")
        self._credentials[ref_name] = value
        self.save()

    def unset(self, ref_name: str) -> None:
        """TS seam write path (`CredentialProvider.unset`); removing an absent reference is a no-op."""
        self._assert_unshadowed(ref_name, "unset")
        if ref_name not in self._credentials:
            return
        del self._credentials[ref_name]
        self.save()

    def set_credential(self, ref_name: str, value: str, save_to_disk: bool = True) -> None:
        """Backward-compatible alias of the TS `set` seam method."""
        if not isinstance(value, str) or len(value) == 0:
            raise ValueError(
                'credentials-local: an empty value cannot be stored for "{}"; use unset'.format(ref_name)
            )
        self._assert_unshadowed(ref_name, "set")
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

        # 3. Discovered .env fallback layers (project over user home)
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
