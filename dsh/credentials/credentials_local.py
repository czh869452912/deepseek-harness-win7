"""
File-backed credentials provider over `$DSH_HOME/.credentials.yaml`.
1:1 with reference @deepseek-ai/dsh-credentials-local and @deepseek-ai/dsh-credentials.
Python 3.8.10 compatible.
"""

import copy
import json
import math
import os
import re
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import yaml

from dsh.cordis.environment import LaunchEnvironmentSnapshot, resolve_dsh_home
from dsh.cordis.file_lock import FileLock
from dsh.cordis.plugin import Plugin
from dsh.credentials.credentials import (
    CredentialProvider,
    credential_key,
    credential_ref,
    is_credential_key_segment,
    is_credential_ref_name,
    parse_credential_key,
)
from dsh.credentials.types import (
    ApiKeyRecord,
    CredentialInfo,
    CredentialRecord,
    CredentialRecordEntry,
    CredentialRecordInfo,
    GrantRecord,
    ResolvedCredential,
)

CREDENTIALS_FILENAME = ".credentials.yaml"
DOCUMENT_VERSION = 1
GROUP_OTHER_BITS = 0o077
DOCUMENT_LOCK_WAIT_MS = 30000


def assert_owner_only(filename: str) -> None:
    """
    Reject credentials document if readable by group/others on POSIX.
    Skipped on Windows.
    """
    if sys.platform == "win32":
        return
    try:
        st = os.stat(filename)
        mode = st.st_mode
    except FileNotFoundError:
        return
    except OSError as error:
        raise error

    offending = mode & GROUP_OTHER_BITS
    if offending != 0:
        raise ValueError(
            f'credentials-local: {filename} is readable beyond its owner (mode {oct(mode & 0o777)}); '
            f'run "chmod 600 {filename}" before starting again'
        )


def assert_json_value(where: str, value: Any, seen: Optional[Set[int]] = None) -> None:
    """Reject payloads that cannot survive JSON round-tripping."""
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)):
        if math.isfinite(value):
            return
        raise TypeError(f"credentials-local: {where} holds a non-finite number")
    if isinstance(value, (dict, list)):
        if seen is None:
            seen = set()
        obj_id = id(value)
        if obj_id in seen:
            raise TypeError(f"credentials-local: {where} is cyclic")
        seen.add(obj_id)
        if isinstance(value, dict):
            for v in value.values():
                assert_json_value(where, v, seen)
        else:
            for v in value:
                assert_json_value(where, v, seen)
        seen.remove(obj_id)
        return
    raise TypeError(f"credentials-local: {where} holds a value JSON cannot represent")


def assert_storable_api_key(key: str, record: ApiKeyRecord) -> None:
    """Validate storable api-key record fields."""
    rec_key = record.get("key")
    if rec_key is not None and (not isinstance(rec_key, str) or len(rec_key) == 0):
        raise TypeError(f'credentials-local: record "{key}" has an empty key; omit the field instead')
    env = record.get("env")
    if env is not None:
        if not isinstance(env, dict):
            raise TypeError(f'credentials-local: record "{key}" env must be a dictionary')
        for name, value in env.items():
            credential_ref(name)
            if not isinstance(value, str) or len(value) == 0:
                raise TypeError(f'credentials-local: record "{key}" env "{name}" must be a non-empty string')


def render_flat_layout_migration(text: str) -> Optional[str]:
    """Render version 1 layout for recognized pre-release flat document."""
    try:
        data = yaml.safe_load(text)
    except Exception:
        return None
    if not isinstance(data, dict) or len(data) == 0:
        return None
    if "version" in data:
        return None
    for line in text.split("\n"):
        if re.match(r"^(%|---|\.\.\.)", line.strip()):
            return None
    for k, v in data.items():
        if not isinstance(k, str) or k == "version":
            return None
        if not is_credential_ref_name(k):
            return None
        if not isinstance(v, str) or len(v) == 0:
            return None

    lines = text.split("\n")
    indented = "\n".join("  " + line if line else line for line in lines)
    if not text.endswith("\n"):
        indented += "\n"
    return f"version: {DOCUMENT_VERSION}\nrefs:\n{indented}"


def parse_credentials_document(text: str, filename: str) -> Dict[str, Any]:
    """Parse credentials document enforcing versioning and strict schema."""
    if not text or not text.strip():
        return {"refs": {}, "records": {}}
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        raise ValueError(f"credentials-local: invalid document at {filename}: {e}")

    if data is None:
        return {"refs": {}, "records": {}}

    if not isinstance(data, dict) or isinstance(data, list):
        raise TypeError(f"credentials-local: {filename} must be a mapping")

    keys = list(data.keys())
    if len(keys) == 0:
        return {"refs": {}, "records": {}}

    if "version" not in data:
        raise ValueError(
            f"credentials-local: {filename} uses the pre-release flat layout. Add `version: {DOCUMENT_VERSION}`"
            f" and nest the existing {len(keys)} {'entry' if len(keys) == 1 else 'entries'} under `refs:`."
            " No values need to change."
        )

    if data["version"] != DOCUMENT_VERSION:
        raise ValueError(
            f"credentials-local: {filename} declares version {json.dumps(data['version'])};"
            f" this build reads version {DOCUMENT_VERSION}"
        )

    for k in keys:
        if k not in ("version", "refs", "records"):
            raise ValueError(f'credentials-local: unknown top-level key "{k}" in {filename}')

    refs_section = data.get("refs") or {}
    refs_map: Dict[str, str] = {}
    if refs_section is not None:
        if not isinstance(refs_section, dict):
            raise TypeError(f'credentials-local: "refs" in {filename} must be a mapping')
        for k, v in refs_section.items():
            credential_ref(k)
            if not isinstance(v, str):
                raise TypeError(f'credentials-local: the value for "{k}" in {filename} must be a string')
            if len(v) == 0:
                raise ValueError(f'credentials-local: the value for "{k}" in {filename} is empty; remove the key instead')
            refs_map[k] = v

    records_section = data.get("records") or {}
    records_map: Dict[str, CredentialRecord] = {}
    if records_section is not None:
        if not isinstance(records_section, dict):
            raise TypeError(f'credentials-local: "records" in {filename} must be a mapping')
        for k, v in records_section.items():
            parse_credential_key(k)
            records_map[k] = parse_record(k, v, filename)

    return {"refs": refs_map, "records": records_map}


def parse_record(key: str, value: Any, filename: str) -> CredentialRecord:
    """Parse and validate one record mapping."""
    if not isinstance(value, dict) or isinstance(value, list):
        raise TypeError(f'credentials-local: record "{key}" in {filename} must be a mapping')

    kind = value.get("kind")
    if kind == "api-key":
        for field in value.keys():
            if field not in ("kind", "key", "env"):
                raise ValueError(f'credentials-local: record "{key}" in {filename} has unknown field "{field}"')
        apiKey = value.get("key")
        if apiKey is not None and (not isinstance(apiKey, str) or len(apiKey) == 0):
            raise TypeError(f'credentials-local: record "{key}" in {filename} has a non-string or empty key')
        env_raw = value.get("env")
        env_parsed = None
        if env_raw is not None:
            if not isinstance(env_raw, dict):
                raise TypeError(f'credentials-local: record "{key}" in {filename} has a non-mapping env')
            env_parsed = {}
            for name, val in env_raw.items():
                credential_ref(name)
                if not isinstance(val, str) or len(val) == 0:
                    raise TypeError(f'credentials-local: record "{key}" env "{name}" in {filename} must be a non-empty string')
                env_parsed[name] = val
        res: ApiKeyRecord = {"kind": "api-key"}
        if apiKey is not None:
            res["key"] = apiKey
        if env_parsed is not None:
            res["env"] = env_parsed
        return res

    if kind == "grant":
        for field in value.keys():
            if field not in ("kind", "payload"):
                raise ValueError(f'credentials-local: record "{key}" in {filename} has unknown field "{field}"')
        if "payload" not in value:
            raise ValueError(f'credentials-local: record "{key}" in {filename} has no payload')
        assert_json_value(f'record "{key}" payload in {filename}', value["payload"])
        return {"kind": "grant", "payload": value["payload"]}

    if kind is None:
        raise ValueError(f'credentials-local: record "{key}" in {filename} has no kind')
    raise ValueError(f'credentials-local: record "{key}" in {filename} has unknown kind {json.dumps(kind)}')


def ensure_cold_start(dsh_home: Optional[str] = None) -> Tuple[str, str]:
    """Ensure ~/.dsh/settings.yaml, ~/.dsh/.credentials.yaml, and ~/.dsh/credentials.json exist."""
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
                        f.write(f"version: {DOCUMENT_VERSION}\nrefs: {{}}\nrecords: {{}}\n")
        except Exception:
            pass

    return settings_yaml, creds_json


class CredentialsService(CredentialProvider):
    """
    File-backed credentials provider implementation (`ctx.credentials`).
    Alias: LocalCredentialProvider.
    """

    def __init__(self, ctx: Optional[Any] = None, credentials_file: Optional[str] = None, config: Optional[Dict[str, Any]] = None):
        super().__init__(ctx)
        cfg = config or {}
        if credentials_file:
            self.filepath = os.path.abspath(credentials_file)
        elif cfg.get("path"):
            self.filepath = os.path.abspath(cfg["path"])
        else:
            home_dir = resolve_dsh_home(cfg.get("dshHome"))
            self.filepath = os.path.abspath(os.path.join(home_dir, CREDENTIALS_FILENAME))

        self.lock_path = self.filepath + ".lock"
        self._lock = threading.RLock()
        self._credentials: Dict[str, str] = {}
        self._records: Dict[str, CredentialRecord] = {}
        self._text: Optional[str] = None
        self._closed: bool = False

        self.prepare_document()
        self.load()

    def prepare_document(self) -> str:
        """Ensure document file exists under lock."""
        with self._lock:
            os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
            if not os.path.exists(self.filepath):
                lock = FileLock(self.lock_path, timeout=5)
                try:
                    with lock:
                        if not os.path.exists(self.filepath):
                            with open(self.filepath, "w", encoding="utf-8") as f:
                                f.write(f"version: {DOCUMENT_VERSION}\nrefs: {{}}\nrecords: {{}}\n")
                except Exception:
                    pass
        return self.filepath

    def close(self) -> None:
        self._closed = True

    def _inherited(self, ref: str) -> Optional[str]:
        """Check process environment for inherited reference value."""
        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("launch_environment"):
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = launch_env.get_from(ref, ["process"])
            if entry and entry.value and len(entry.value) > 0:
                return entry.value
        val = os.environ.get(ref)
        if val and len(val) > 0:
            return val
        return None

    def _dotenv_fallback(self, ref: str) -> Optional[Any]:
        """Check project and user .env fallbacks."""
        if self.ctx and hasattr(self.ctx, "has") and self.ctx.has("launch_environment"):
            launch_env: LaunchEnvironmentSnapshot = self.ctx.get("launch_environment")
            entry = launch_env.get_from(ref, ["project-env", "user-env"])
            if entry and entry.value and len(entry.value) > 0:
                return entry
        return None

    def _assert_unshadowed(self, ref_name: str, verb: str) -> None:
        if self._inherited(ref_name) is not None:
            raise ValueError(
                f'credentials-local: "{ref_name}" is supplied read-only by the launching environment, so {verb} would be'
                " shadowed; unset it in the shell you start dsh from instead"
            )

    def load(self) -> None:
        """Load and parse document from disk."""
        with self._lock:
            assert_owner_only(self.filepath)
            if not os.path.exists(self.filepath):
                return
            lock = FileLock(self.lock_path, timeout=5)
            try:
                with lock:
                    self.reconcile_from_disk()
            except Exception as e:
                ctx = getattr(self, "ctx", None)
                logger = getattr(ctx, "logger", None) if ctx else None
                if logger:
                    logger.warn("Failed to load credentials from %s: %s", self.filepath, e)

    def reconcile_from_disk(self) -> None:
        """Compare disk content against memory and emit updates."""
        assert_owner_only(self.filepath)
        if not os.path.exists(self.filepath):
            text = None
        else:
            with open(self.filepath, "r", encoding="utf-8") as f:
                text = f.read()

        if text == self._text or self._closed:
            return

        if text is None:
            next_refs: Dict[str, str] = {}
            next_records: Dict[str, CredentialRecord] = {}
        else:
            migrated = render_flat_layout_migration(text)
            if migrated is not None:
                text = migrated
                with open(self.filepath, "w", encoding="utf-8") as f:
                    f.write(migrated)
            doc = parse_credentials_document(text, self.filepath)
            next_refs = doc["refs"]
            next_records = doc["records"]

        prev_refs = self._credentials
        prev_records = self._records

        self._text = text
        self._credentials = next_refs
        self._records = next_records

        # Detect changes and fire notifications
        all_refs = set(prev_refs.keys()) | set(next_refs.keys())
        for ref in all_refs:
            if prev_refs.get(ref) != next_refs.get(ref):
                self.notify_updated(ref)

        all_records = set(prev_records.keys()) | set(next_records.keys())
        for rk in all_records:
            if prev_records.get(rk) != next_records.get(rk):
                self.notify_record_updated(rk)

    def save(self) -> None:
        """Persist memory snapshot to disk under lock."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
                doc: Dict[str, Any] = {"version": DOCUMENT_VERSION, "refs": dict(self._credentials)}
                if self._records:
                    doc["records"] = dict(self._records)
                text = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
                with open(self.filepath, "w", encoding="utf-8") as f:
                    f.write(text)
                self._text = text

    # ---- Reference Seam Methods ----

    def resolve(self, ref: str) -> Optional[ResolvedCredential]:
        credential_ref(ref)
        inherited = self._inherited(ref)
        if inherited is not None:
            return ResolvedCredential(inherited, "env")
        stored = self._credentials.get(ref)
        if stored is not None and len(stored) > 0:
            return ResolvedCredential(stored, "file")
        fallback = self._dotenv_fallback(ref)
        if fallback is not None:
            return ResolvedCredential(fallback.value, fallback.source)
        return None

    def describe(self, ref: str) -> CredentialInfo:
        credential_ref(ref)
        if self._inherited(ref) is not None:
            return CredentialInfo(configured=True, writable=False, source="env")
        stored = self._credentials.get(ref)
        if stored is not None and len(stored) > 0:
            return CredentialInfo(configured=True, writable=True, source="file")
        fallback = self._dotenv_fallback(ref)
        if fallback is not None:
            return CredentialInfo(configured=True, writable=True, source=fallback.source)
        return CredentialInfo(configured=False, writable=True)

    def set(self, ref: str, value: str) -> None:
        credential_ref(ref)
        if not isinstance(value, str) or len(value) == 0:
            raise ValueError(f'credentials-local: an empty value cannot be stored for "{ref}"; use unset')
        self._assert_unshadowed(ref, "set")
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self.reconcile_from_disk()
                self._credentials[ref] = value
                self.save()
                self.notify_updated(ref)

    def unset(self, ref: str) -> None:
        credential_ref(ref)
        self._assert_unshadowed(ref, "unset")
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self.reconcile_from_disk()
                if ref not in self._credentials:
                    return
                del self._credentials[ref]
                self.save()
                self.notify_updated(ref)

    def set_credential(self, ref_name: str, value: str, save_to_disk: bool = True) -> None:
        if save_to_disk:
            self.set(ref_name, value)
        else:
            credential_ref(ref_name)
            self._assert_unshadowed(ref_name, "set")
            self._credentials[ref_name] = value

    # ---- Record Seam Methods (<scope>/<id>) ----

    def read_record(self, key: str) -> Optional[Dict[str, Any]]:
        parse_credential_key(key)
        rec = self._records.get(key)
        return copy.deepcopy(rec) if rec is not None else None

    def describe_record(self, key: str) -> CredentialRecordInfo:
        parse_credential_key(key)
        rec = self._records.get(key)
        if rec is None:
            return CredentialRecordInfo(configured=False, writable=True)
        kind = rec.get("kind")
        return CredentialRecordInfo(configured=True, writable=True, kind=kind)

    def list_records(self) -> List[CredentialRecordEntry]:
        res = []
        for k, rec in self._records.items():
            parse_credential_key(k)
            kind = rec.get("kind", "api-key")
            res.append(CredentialRecordEntry(key=k, kind=kind))
        return res

    def modify_record(
        self,
        key: str,
        mutate: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        parse_credential_key(key)
        if self._closed:
            raise ValueError(f'credentials-local is disposed: cannot modify "{key}"')
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self.reconcile_from_disk()
                current = copy.deepcopy(self._records.get(key))
                nxt = mutate(current)
                if nxt is None:
                    return current
                if not isinstance(nxt, dict) or "kind" not in nxt:
                    raise TypeError(f'credentials-local: record "{key}" must be a dictionary with a "kind"')
                kind = nxt.get("kind")
                if kind == "grant":
                    assert_json_value(f'record "{key}" payload', nxt.get("payload"))
                elif kind == "api-key":
                    assert_storable_api_key(key, nxt)
                else:
                    raise ValueError(f'credentials-local: record "{key}" has unknown kind {json.dumps(kind)}')

                self._records[key] = copy.deepcopy(nxt)
                self.save()
                self.notify_record_updated(key)
                return copy.deepcopy(nxt)

    def delete_record(self, key: str) -> None:
        parse_credential_key(key)
        if self._closed:
            raise ValueError(f'credentials-local is disposed: cannot delete "{key}"')
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self.reconcile_from_disk()
                if key not in self._records:
                    return
                del self._records[key]
                self.save()
                self.notify_record_updated(key)


LocalCredentialProvider = CredentialsService


class CredentialsLocalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-credentials-local`: Mounts local credentials management service (`ctx.credentials`).
    """

    id = "credentials-local"
    name = "@deepseek-ai/dsh-credentials-local"

    def apply(self, ctx: Any) -> None:
        cfg = self.config or {}
        credentials_file = cfg.get("credentialsFile", cfg.get("path"))
        creds_service = CredentialsService(ctx=ctx, credentials_file=credentials_file, config=cfg)

        initial_creds = cfg.get("credentials", {})
        for ref_name, val in initial_creds.items():
            creds_service._credentials[ref_name] = str(val)

        # CredentialsService registers its canonical `credentials` service
        # through the Cordis Service base constructor. Re-registering here
        # would fail strict duplicate-service checks during harness boot.
