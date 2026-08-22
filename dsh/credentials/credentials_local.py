"""
File-backed credentials provider (`ctx.credentials`).
1:1 with official `@deepseek-ai/dsh-credentials` and `@deepseek-ai/dsh-credentials-local`.
"""

import copy
import json
import os
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import yaml
from dsh.cordis.file_lock import FileLock

from dsh.cordis.environment import resolve_dsh_home, LaunchEnvironmentSnapshot
from dsh.cordis.plugin import Plugin

CREDENTIALS_FILENAME = ".credentials.yaml"
DOCUMENT_VERSION = 1
REF_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KEY_SEGMENT_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def is_credential_ref_name(value: str) -> bool:
    """Whether a raw string could name a credential reference at all."""
    return bool(REF_PATTERN.match(value))


def is_credential_key_segment(value: str) -> bool:
    """Whether a raw string could be a valid credential key segment."""
    return bool(KEY_SEGMENT_PATTERN.match(value))


def credential_key(scope: str, id_segment: str) -> str:
    """Brand scope and id segment as a credential key (<scope>/<id>)."""
    if not is_credential_key_segment(scope):
        raise TypeError(f'credential key scope "{scope}" must be a lowercase hyphenated identifier')
    if not is_credential_key_segment(id_segment):
        raise TypeError(f'credential key id "{id_segment}" must be a lowercase hyphenated identifier')
    return f"{scope}/{id_segment}"


def parse_credential_key(value: str) -> Tuple[str, str]:
    """Parse a stored <scope>/<id> string into scope and id segments."""
    parts = value.split("/")
    if len(parts) != 2:
        raise TypeError(f'credential key "{value}" must be "<scope>/<id>"')
    scope, id_segment = parts
    if not is_credential_key_segment(scope) or not is_credential_key_segment(id_segment):
        raise TypeError(f'credential key "{value}" has invalid scope or id segment')
    return scope, id_segment


def ensure_cold_start(dsh_home: Optional[str] = None) -> Tuple[str, str]:
    """
    Ensure ~/.dsh/settings.yaml and ~/.dsh/credentials.json (or .credentials.yaml)
    are automatically prepared with valid default maps when absent.
    """
    home_dir = resolve_dsh_home(dsh_home)
    os.makedirs(home_dir, exist_ok=True)

    settings_yaml = os.path.join(home_dir, "settings.yaml")
    if not os.path.exists(settings_yaml):
        lock = FileLock(settings_yaml + ".lock", timeout=5)
        try:
            with lock:
                if not os.path.exists(settings_yaml):
                    with open(settings_yaml, "w", encoding="utf-8") as f:
                        f.write("# DeepSeek Harness Settings\n{}\n")
        except Exception:
            pass

    creds_json = os.path.join(home_dir, "credentials.json")
    if not os.path.exists(creds_json):
        lock = FileLock(creds_json + ".lock", timeout=5)
        try:
            with lock:
                if not os.path.exists(creds_json):
                    with open(creds_json, "w", encoding="utf-8") as f:
                        f.write("{}\n")
        except Exception:
            pass

    creds_yaml = os.path.join(home_dir, CREDENTIALS_FILENAME)
    if not os.path.exists(creds_yaml):
        lock = FileLock(creds_yaml + ".lock", timeout=5)
        try:
            with lock:
                if not os.path.exists(creds_yaml):
                    with open(creds_yaml, "w", encoding="utf-8") as f:
                        f.write("version: 1\nrefs: {}\nrecords: {}\n")
        except Exception:
            pass

    return settings_yaml, creds_json


class CredentialsService:
    """
    Credentials Service registered at `ctx.credentials`.
    Manages resolution and persistence of sensitive credentials and records.
    """

    def __init__(self, ctx: Optional[Any] = None, credentials_file: Optional[str] = None):
        self.ctx = ctx
        self._credentials: Dict[str, str] = {}
        self._records: Dict[str, Any] = {}
        self._format: str = "yaml"
        self._closed: bool = False

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

        self.lock_path = self.filepath + ".lock"
        self._lock = threading.RLock()

        # Cold-start file creation
        self.prepare_document()

        self.load()

    def prepare_document(self) -> str:
        """Ensure local credentials document exists with a valid default map."""
        with self._lock:
            os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
            if not os.path.exists(self.filepath):
                lock = FileLock(self.lock_path, timeout=5)
                try:
                    with lock:
                        if not os.path.exists(self.filepath):
                            with open(self.filepath, "w", encoding="utf-8") as f:
                                if self._format == "json":
                                    f.write("{}\n")
                                else:
                                    f.write(f"version: {DOCUMENT_VERSION}\nrefs: {{}}\nrecords: {{}}\n")
                except Exception:
                    pass
        return self.filepath

    def close(self) -> None:
        self._closed = True

    def _log(self, level: str, message: str) -> None:
        logger = getattr(self.ctx, "logger", None) if self.ctx else None
        if logger is not None:
            try:
                getattr(logger, level)(message)
                return
            except Exception:
                pass

    def _load_unlocked(self) -> None:
        if not os.path.exists(self.filepath):
            return
        with open(self.filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if self._format == "json":
            data = json.loads(content) if content.strip() else {}
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str):
                        self._credentials[k] = v
            return
        self._load_yaml(content)

    def load(self) -> None:
        """Boot read: load document under lock."""
        with self._lock:
            if not os.path.exists(self.filepath):
                return
            lock = FileLock(self.lock_path, timeout=5)
            try:
                with lock:
                    self._load_unlocked()
            except Exception as e:
                self._log("warn", f"Failed to load credentials from {self.filepath}: {e}")

    def _load_yaml(self, content: str) -> None:
        try:
            data = yaml.safe_load(content)
        except Exception as e:
            raise ValueError(f"credentials-local: invalid document at {self.filepath}: {e}")
        if data is None:
            data = {}
        if not isinstance(data, dict) or isinstance(data, list):
            raise TypeError(f"credentials-local: {self.filepath} must be a mapping")
        if len(data) == 0:
            return
        if "version" not in data:
            if self._is_flat_layout(data):
                self._credentials = dict(data)
                self._save_unlocked()
                self._log("info", f"credentials-local: migrated {self.filepath} to version {DOCUMENT_VERSION} layout")
                return
            keys = list(data.keys())
            raise ValueError(
                f"credentials-local: {self.filepath} uses the pre-release flat layout. Add `version: {DOCUMENT_VERSION}`"
                f" and nest the existing {len(keys)} entries under `refs:`."
            )
        if data["version"] != DOCUMENT_VERSION:
            raise ValueError(f"credentials-local: {self.filepath} declares version {data['version']}; build reads {DOCUMENT_VERSION}")
        for key in data.keys():
            if key not in ("version", "refs", "records"):
                raise ValueError(f'credentials-local: unknown top-level key "{key}" in {self.filepath}')
        refs = data.get("refs") or {}
        if not isinstance(refs, dict):
            raise TypeError(f'credentials-local: "refs" in {self.filepath} must be a mapping')
        for k, v in refs.items():
            if not isinstance(v, str):
                raise TypeError(f'credentials-local: value for "{k}" in {self.filepath} must be a string')
            if len(v) == 0:
                raise ValueError(f'credentials-local: value for "{k}" in {self.filepath} is empty')
            self._credentials[k] = v
        records = data.get("records") or {}
        if isinstance(records, dict):
            self._records = dict(records)

    def _is_flat_layout(self, data: Dict[str, Any]) -> bool:
        for k, v in data.items():
            if not isinstance(k, str) or not is_credential_ref_name(k) or k == "version":
                return False
            if not isinstance(v, str) or len(v) == 0:
                return False
        return True

    def _save_unlocked(self) -> None:
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        if self._format == "json":
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self._credentials, f, indent=2, ensure_ascii=False)
                f.write("\n")
            return
        document: Dict[str, Any] = {"version": DOCUMENT_VERSION, "refs": dict(self._credentials)}
        if self._records:
            document["records"] = dict(self._records)
        with open(self.filepath, "w", encoding="utf-8") as f:
            yaml.dump(document, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def save(self) -> None:
        """Durably persist credentials to disk under lock."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self._save_unlocked()

    def _assert_unshadowed(self, ref_name: str, verb: str) -> None:
        if ref_name in os.environ and os.environ[ref_name]:
            raise ValueError(
                f'credentials-local: "{ref_name}" is supplied read-only by the launching environment, so {verb} would be'
                " shadowed; unset it in the shell you start dsh from instead"
            )

    def resolve(self, ref_name: str) -> Optional[str]:
        if ref_name in os.environ and os.environ[ref_name]:
            return os.environ[ref_name]

        if ref_name in self._credentials and self._credentials[ref_name]:
            return self._credentials[ref_name]

        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("launch_environment"):
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = launch_env.get_from(ref_name, ["project-env", "user-env"])
            if entry and entry.value:
                return entry.value

        return None

    def describe(self, ref_name: str) -> Dict[str, Any]:
        if ref_name in os.environ and os.environ[ref_name]:
            return {"configured": True, "source": "env", "writable": False}
        if ref_name in self._credentials and self._credentials[ref_name]:
            return {"configured": True, "source": "file", "writable": True}
        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("launch_environment"):
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = launch_env.get_from(ref_name, ["project-env", "user-env"])
            if entry and entry.value:
                return {"configured": True, "source": entry.source, "writable": True}
        return {"configured": False, "source": None, "writable": True}

    def set(self, ref_name: str, value: str) -> None:
        if not isinstance(value, str) or len(value) == 0:
            raise ValueError(f'credentials-local: an empty value cannot be stored for "{ref_name}"; use unset')
        self._assert_unshadowed(ref_name, "set")
        self._credentials[ref_name] = value
        self.save()
        if self.ctx and hasattr(self.ctx, "emit"):
            try:
                self.ctx.emit("credentials/reference-updated", ref_name)
            except Exception:
                pass

    def unset(self, ref_name: str) -> None:
        self._assert_unshadowed(ref_name, "unset")
        if ref_name not in self._credentials:
            return
        del self._credentials[ref_name]
        self.save()
        if self.ctx and hasattr(self.ctx, "emit"):
            try:
                self.ctx.emit("credentials/reference-updated", ref_name)
            except Exception:
                pass

    def set_credential(self, ref_name: str, value: str, save_to_disk: bool = True) -> None:
        if not isinstance(value, str) or len(value) == 0:
            raise ValueError(f'credentials-local: an empty value cannot be stored for "{ref_name}"; use unset')
        self._assert_unshadowed(ref_name, "set")
        self._credentials[ref_name] = value
        if save_to_disk:
            self.save()
            if self.ctx and hasattr(self.ctx, "emit"):
                try:
                    self.ctx.emit("credentials/reference-updated", ref_name)
                except Exception:
                    pass

    # ---- Key Space Record Management (<scope>/<id>) 1:1 with TS ----

    def read_record(self, key: str) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._records.get(key))

    def readRecord(self, key: str) -> Optional[Dict[str, Any]]:
        return self.read_record(key)

    def describe_record(self, key: str) -> Dict[str, Any]:
        rec = self._records.get(key)
        if rec is None:
            return {"configured": False, "writable": True}
        kind = rec.get("kind") if isinstance(rec, dict) else None
        return {"configured": True, "kind": kind, "writable": True}

    def describeRecord(self, key: str) -> Dict[str, Any]:
        return self.describe_record(key)

    def list_records(self) -> List[Dict[str, Any]]:
        res = []
        for k, rec in self._records.items():
            kind = rec.get("kind") if isinstance(rec, dict) else None
            res.append({"key": k, "kind": kind})
        return res

    def listRecords(self) -> List[Dict[str, Any]]:
        return self.list_records()

    def modify_record(self, key: str, mutate_fn: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
        """Serialized read-modify-write over key record under file lock."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self._load_unlocked()
                current = copy.deepcopy(self._records.get(key))
                nxt = mutate_fn(current)
                if nxt is None:
                    return current
                if not isinstance(nxt, dict) or "kind" not in nxt:
                    raise TypeError(f'credentials-local: record "{key}" must be a dictionary with a "kind"')
                self._records[key] = copy.deepcopy(nxt)
                self._save_unlocked()
                if self.ctx and hasattr(self.ctx, "emit"):
                    try:
                        self.ctx.emit("credentials/record-updated", key)
                    except Exception:
                        pass
                return copy.deepcopy(nxt)

    def modifyRecord(self, key: str, mutate_fn: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
        return self.modify_record(key, mutate_fn)

    def delete_record(self, key: str) -> None:
        """Remove record key and notify subscribers."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self._load_unlocked()
                if key in self._records:
                    del self._records[key]
                    self._save_unlocked()
                    if self.ctx and hasattr(self.ctx, "emit"):
                        try:
                            self.ctx.emit("credentials/record-updated", key)
                        except Exception:
                            pass

    def deleteRecord(self, key: str) -> None:
        self.delete_record(key)


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
