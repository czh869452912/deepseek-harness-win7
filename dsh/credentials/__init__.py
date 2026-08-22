"""
Credentials and Authorization capability family.
1:1 with reference @deepseek-ai/dsh-credentials, dsh-credentials-local, and dsh-authorization.
"""

from dsh.credentials.authorization import (
    AuthorizationDeclinedError,
    AuthorizationError,
    AuthorizationFlow,
    AuthorizationSession,
    AuthorizationService,
)
from dsh.credentials.credentials import (
    CredentialProvider,
    credentialKey,
    credentialKeyId,
    credentialKeyScope,
    credentialRef,
    credential_key,
    credential_key_id,
    credential_key_scope,
    credential_ref,
    isCredentialKeySegment,
    isCredentialRefName,
    is_credential_key_segment,
    is_credential_ref_name,
    parseCredentialKey,
    parse_credential_key,
)
from dsh.credentials.credentials_local import (
    CredentialsLocalPlugin,
    CredentialsService,
    LocalCredentialProvider,
    assert_owner_only,
    ensure_cold_start,
    parse_credentials_document,
)
from dsh.credentials.invariant import (
    apply_authorization_invariant,
    apply_credentials_invariant,
)
from dsh.credentials.types import (
    ApiKeyRecord,
    AuthorizationEntry,
    AuthorizationMethod,
    AuthorizationNotice,
    AuthorizationOutcome,
    AuthorizationPrompt,
    AuthorizationPromptOption,
    CredentialInfo,
    CredentialRecord,
    CredentialRecordEntry,
    CredentialRecordInfo,
    GrantRecord,
    ResolvedCredential,
)

__all__ = [
    # Seam Base
    "CredentialProvider",
    "ResolvedCredential",
    "CredentialInfo",
    "CredentialRecordInfo",
    "CredentialRecordEntry",
    "ApiKeyRecord",
    "GrantRecord",
    "CredentialRecord",
    # Helper Functions & Aliases
    "credential_ref",
    "credentialRef",
    "is_credential_ref_name",
    "isCredentialRefName",
    "is_credential_key_segment",
    "isCredentialKeySegment",
    "credential_key",
    "credentialKey",
    "parse_credential_key",
    "parseCredentialKey",
    "credential_key_scope",
    "credentialKeyScope",
    "credential_key_id",
    "credentialKeyId",
    # Local Provider
    "CredentialsService",
    "LocalCredentialProvider",
    "CredentialsLocalPlugin",
    "ensure_cold_start",
    "assert_owner_only",
    "parse_credentials_document",
    # Authorization
    "AuthorizationService",
    "AuthorizationError",
    "AuthorizationDeclinedError",
    "AuthorizationFlow",
    "AuthorizationSession",
    "AuthorizationEntry",
    "AuthorizationMethod",
    "AuthorizationNotice",
    "AuthorizationPrompt",
    "AuthorizationPromptOption",
    "AuthorizationOutcome",
    # Invariants
    "apply_credentials_invariant",
    "apply_authorization_invariant",
]
