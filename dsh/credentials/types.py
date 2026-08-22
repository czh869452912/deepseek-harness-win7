"""
Credentials and Authorization type definitions.
1:1 with reference @deepseek-ai/dsh-credentials/types and @deepseek-ai/dsh-authorization/types.
Python 3.8.10 compatible.
"""

from typing import Any, Dict, List, Optional, Union


class ResolvedCredential(dict):
    """One resolved credential value and the source layer that supplied it."""

    def __init__(self, value: str, source: str):
        super().__init__(value=value, source=source)
        self.value = value
        self.source = source

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.value == other
        return super().__eq__(other)

    def __repr__(self) -> str:
        return f"ResolvedCredential(value={self.value!r}, source={self.source!r})"


class CredentialInfo(dict):
    """Source and writability facts for one reference, safe for configuration UIs — never the value."""

    def __init__(self, configured: bool, writable: bool, source: Optional[str] = None):
        d = {"configured": configured, "writable": writable}
        if source is not None:
            d["source"] = source
        super().__init__(d)
        self.configured = configured
        self.writable = writable
        self.source = source


class CredentialRecordInfo(dict):
    """Presence and writability facts for one record, safe for configuration UIs — never the value."""

    def __init__(self, configured: bool, writable: bool, kind: Optional[str] = None):
        d = {"configured": configured, "writable": writable}
        if kind is not None:
            d["kind"] = kind
        super().__init__(d)
        self.configured = configured
        self.writable = writable
        self.kind = kind


class CredentialRecordEntry(dict):
    """One stored record's address and tag, for enumeration — never its value."""

    def __init__(self, key: str, kind: str):
        super().__init__(key=key, kind=kind)
        self.key = key
        self.kind = kind


ApiKeyRecord = Dict[str, Any]
GrantRecord = Dict[str, Any]
CredentialRecord = Dict[str, Any]

AuthorizationMethod = Dict[str, str]
AuthorizationNotice = Dict[str, Any]
AuthorizationPromptOption = Dict[str, Any]
AuthorizationPrompt = Dict[str, Any]
AuthorizationOutcome = Dict[str, str]
AuthorizationEntry = Dict[str, Any]
