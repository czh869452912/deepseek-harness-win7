"""
Per-harness-home anonymous user id shared by telemetry and feedback.
1:1 with reference @deepseek-ai/dsh-anonymous-user-id.
Python 3.8.10 compatible.
"""

import os
import re
from typing import Any, Callable, Dict, Optional
import uuid

from dsh.cordis.environment import resolve_dsh_home

AnonymousUserId = str
ANONYMOUS_USER_ID_FILE_NAME = ".anonymous-user-id"
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

_memo: Dict[str, AnonymousUserId] = {}


def _read_persisted_id(file_path: str) -> Optional[AnonymousUserId]:
    """Read a valid persisted id from the file, or None when absent/corrupt."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return None
    val = text.strip()
    return val if bool(UUID_PATTERN.match(val)) else None


def get_or_create_anonymous_user_id(options: Optional[Dict[str, Any]] = None) -> AnonymousUserId:
    """
    Return the harness home's anonymous user id, creating and persisting one on first use.
    Scoped to harness home ($DSH_HOME > ~/.dsh).
    """
    opts = options or {}
    env = opts.get("env")
    dsh_home = resolve_dsh_home(None, env)
    file_path = os.path.abspath(os.path.join(dsh_home, ANONYMOUS_USER_ID_FILE_NAME))

    if file_path in _memo:
        return _memo[file_path]

    uid = _read_persisted_id(file_path)
    if uid is None:
        generator = opts.get("random_uuid") or opts.get("randomUUID") or (lambda: str(uuid.uuid4()))
        created = str(generator())
        parent_dir = os.path.dirname(file_path)

        try:
            os.makedirs(parent_dir, exist_ok=True)
            with open(file_path, "x", encoding="utf-8") as f:
                f.write(f"{created}\n")
            uid = created
        except FileExistsError:
            uid = _read_persisted_id(file_path)
            if uid is None:
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(f"{created}\n")
                except Exception:
                    pass
                uid = created
        except Exception:
            uid = _read_persisted_id(file_path)
            if uid is None:
                uid = created

    _memo[file_path] = uid
    return uid


def getOrCreateAnonymousUserId(options: Optional[Dict[str, Any]] = None) -> AnonymousUserId:
    return get_or_create_anonymous_user_id(options)
