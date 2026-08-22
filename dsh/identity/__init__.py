"""
Identity subsystem exports.
1:1 with reference @deepseek-ai/dsh-anonymous-user-id and shared user identity resolution.
"""

from dsh.identity.anonymous_user_id import (
    ANONYMOUS_USER_ID_FILE_NAME,
    AnonymousUserId,
    get_or_create_anonymous_user_id,
    getOrCreateAnonymousUserId,
)
from dsh.identity.invariant import apply as apply_anonymous_user_id_invariant
from dsh.identity.user_identity import get_system_user, resolve_author_identity

__all__ = [
    "ANONYMOUS_USER_ID_FILE_NAME",
    "AnonymousUserId",
    "get_or_create_anonymous_user_id",
    "getOrCreateAnonymousUserId",
    "get_system_user",
    "resolve_author_identity",
    "apply_anonymous_user_id_invariant",
]
