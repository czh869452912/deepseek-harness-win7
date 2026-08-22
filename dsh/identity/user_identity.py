"""
User identity resolution and system user fallback utilities.
Python 3.8.10 compatible.
"""

import getpass
import os
from typing import Optional


def get_system_user() -> str:
    """
    Get system username with safe fallbacks across platforms.
    Order: getpass.getuser() -> USER/USERNAME env var -> 'system'.
    """
    try:
        u = getpass.getuser()
        if u and u.strip():
            return u.strip()
    except Exception:
        pass

    env_user = os.environ.get("USER") or os.environ.get("USERNAME")
    if env_user and env_user.strip():
        return env_user.strip()

    return "system"


def resolve_author_identity(user: Optional[str] = None) -> str:
    """
    Resolve user author identity for commits, authoring, and telemetry.
    If provided user is non-empty string, returns it; otherwise falls back to system user.
    """
    if user and isinstance(user, str) and user.strip():
        return user.strip()
    return get_system_user()
