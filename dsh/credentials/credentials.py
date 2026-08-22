"""
Abstract Credential Seam Service and brand grammar helpers.
1:1 with reference @deepseek-ai/dsh-credentials.
Python 3.8.10 compatible.
"""

import re
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from dsh.cordis.service import Service
from dsh.credentials.types import (
    CredentialInfo,
    CredentialRecordEntry,
    CredentialRecordInfo,
    ResolvedCredential,
)

REF_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KEY_SEGMENT_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def is_credential_ref_name(value: str) -> bool:
    """Whether a raw string could name a reference at all."""
    if not isinstance(value, str):
        return False
    return bool(REF_PATTERN.match(value))


def isCredentialRefName(value: str) -> bool:
    return is_credential_ref_name(value)


def credential_ref(value: str) -> str:
    """Brand a raw string as a CredentialRef (POSIX identifier)."""
    if not is_credential_ref_name(value):
        raise TypeError(f'credential ref "{value}" must match {REF_PATTERN.pattern}')
    return value


def credentialRef(value: str) -> str:
    return credential_ref(value)


def is_credential_key_segment(value: str) -> bool:
    """Whether a raw string could be a credentialKey segment."""
    if not isinstance(value, str):
        return False
    return bool(KEY_SEGMENT_PATTERN.match(value))


def isCredentialKeySegment(value: str) -> bool:
    return is_credential_key_segment(value)


def credential_key(scope: str, id_segment: str) -> str:
    """Brand scope and id segment as a CredentialKey (<scope>/<id>)."""
    if not is_credential_key_segment(scope):
        raise TypeError(f'credential key segment "{scope}" must match {KEY_SEGMENT_PATTERN.pattern}')
    if not is_credential_key_segment(id_segment):
        raise TypeError(f'credential key segment "{id_segment}" must match {KEY_SEGMENT_PATTERN.pattern}')
    return f"{scope}/{id_segment}"


def credentialKey(scope: str, id_segment: str) -> str:
    return credential_key(scope, id_segment)


def parse_credential_key(value: str) -> str:
    """Parse and validate a stored <scope>/<id> CredentialKey string."""
    if not isinstance(value, str):
        raise TypeError(f'credential key "{value}" must be "<scope>/<id>"')
    segments = value.split("/")
    if len(segments) != 2:
        raise TypeError(f'credential key "{value}" must be "<scope>/<id>"')
    scope, id_segment = segments
    return credential_key(scope, id_segment)


def parseCredentialKey(value: str) -> str:
    return parse_credential_key(value)


def credential_key_scope(key: str) -> str:
    """Extract scope segment from a valid CredentialKey."""
    idx = key.find("/")
    if idx == -1:
        raise TypeError(f'credential key "{key}" must be "<scope>/<id>"')
    return key[:idx]


def credentialKeyScope(key: str) -> str:
    return credential_key_scope(key)


def credential_key_id(key: str) -> str:
    """Extract id segment from a valid CredentialKey."""
    idx = key.find("/")
    if idx == -1:
        raise TypeError(f'credential key "{key}" must be "<scope>/<id>"')
    return key[idx + 1 :]


def credentialKeyId(key: str) -> str:
    return credential_key_id(key)


class CredentialProvider(Service):
    """
    Abstract credential service registered at `ctx.credentials`.
    1:1 with reference @deepseek-ai/dsh-credentials CredentialProvider.
    """

    name = "credentials"

    def __init__(self, ctx: Optional[Any] = None):
        super().__init__(ctx, "credentials")

    def resolve(self, ref: str) -> Optional[ResolvedCredential]:
        """Resolve one reference to its current value and source."""
        raise NotImplementedError

    def describe(self, ref: str) -> CredentialInfo:
        """Describe one reference for configuration UIs without exposing value."""
        raise NotImplementedError

    def set(self, ref: str, value: str) -> None:
        """Durably store one value in provider-managed writable source."""
        raise NotImplementedError

    def unset(self, ref: str) -> None:
        """Remove one reference from provider-managed writable source."""
        raise NotImplementedError

    def read_record(self, key: str) -> Optional[Dict[str, Any]]:
        """Read one stored record."""
        raise NotImplementedError

    def readRecord(self, key: str) -> Optional[Dict[str, Any]]:
        return self.read_record(key)

    def describe_record(self, key: str) -> CredentialRecordInfo:
        """Describe one record for configuration UIs."""
        raise NotImplementedError

    def describeRecord(self, key: str) -> CredentialRecordInfo:
        return self.describe_record(key)

    def list_records(self) -> List[CredentialRecordEntry]:
        """Enumerate stored record addresses and tags."""
        raise NotImplementedError

    def listRecords(self) -> List[CredentialRecordEntry]:
        return self.list_records()

    def modify_record(
        self,
        key: str,
        mutate: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        """Serialized read-modify-write over one record."""
        raise NotImplementedError

    def modifyRecord(
        self,
        key: str,
        mutate: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        return self.modify_record(key, mutate)

    def delete_record(self, key: str) -> None:
        """Remove one record."""
        raise NotImplementedError

    def deleteRecord(self, key: str) -> None:
        self.delete_record(key)

    def notify_updated(self, ref: str) -> None:
        """Fan credentials/reference-updated out to subscribers."""
        self._fan_out("credentials/reference-updated", ref)

    def notifyUpdated(self, ref: str) -> None:
        self.notify_updated(ref)

    def notify_record_updated(self, key: str) -> None:
        """Fan credentials/record-updated out to subscribers."""
        self._fan_out("credentials/record-updated", key)

    def notifyRecordUpdated(self, key: str) -> None:
        self.notify_record_updated(key)

    def _fan_out(self, event: str, subject: str) -> None:
        """
        Contained dispatch for commit notifications.
        All listeners run; normal errors logged, INVARIANT errors rethrown synchronously.
        """
        invariant_failure: Optional[Exception] = None
        ctx = getattr(self, "ctx", None)
        if ctx is None:
            return

        listeners = []
        if hasattr(ctx, "events") and hasattr(ctx.events, "_dispatch_hooks"):
            listeners = ctx.events._dispatch_hooks("emit", event, ctx)

        for listener in listeners:
            try:
                listener(subject)
            except Exception as error:
                if getattr(error, "code", None) == "INVARIANT":
                    if invariant_failure is None:
                        invariant_failure = error
                    continue
                self._warn_listener_failure(event, subject, error)

        if not listeners and hasattr(ctx, "emit"):
            try:
                ctx.emit(event, subject)
            except Exception as error:
                if getattr(error, "code", None) == "INVARIANT":
                    if invariant_failure is None:
                        invariant_failure = error

        if invariant_failure is not None:
            raise invariant_failure

    def _warn_listener_failure(self, event: str, subject: str, error: Exception) -> None:
        ctx = getattr(self, "ctx", None)
        logger = getattr(ctx, "logger", None) if ctx else None
        if logger:
            try:
                logger.warn('credentials: a %s listener for "%s" failed', event, subject)
                logger.warn(str(error))
            except Exception:
                pass
