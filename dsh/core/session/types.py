"""
Session storage types, constants, and envelope validation.
Ported 1:1 from reference packages/core/session/src/types.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import os
import time
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Sequence, Union

from dsh.core.session.json import (
    UNDEFINED,
    deep_freeze,
    is_json_value,
    snapshot_json_value,
    walk_json_value,
)

SESSION_FORMAT_VERSION = 0


def SessionId(id: str) -> str:
    """Brand a string as a SessionId (identity in Python)."""
    return str(id)


SessionEvent = Dict[str, Any]


ALLOWED_ENVELOPE_KEYS: FrozenSet[str] = frozenset([
    "type",
    "seq",
    "time",
    "data",
    "surfaceOp",
    "sourceEventSeqs",
])

ALLOWED_ADAPTER_DEFAULTS: FrozenSet[str] = frozenset([
    "maxTokens",
    "reasoningEffort",
])


class SessionForkError(ValueError):
    """
    Typed error for session fork rejections.
    Rejection codes: SESSION_NOT_FOUND, SESSION_NOT_LIVE, SESSION_ALREADY_EXISTS, INVALID_BOUNDARY, OPEN_TURN.
    """

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class SessionHeader:
    """
    Immutable storage metadata for a session.
    Supports attribute access (header.id, header.createdAt) and mapping access (header['id']).
    """

    def __init__(
        self,
        session_id: str,
        version: int = SESSION_FORMAT_VERSION,
        created_at: Optional[int] = None,
        cwd: Optional[str] = None,
        parent_session: Optional[str] = None,
        seed_length: Optional[int] = None,
        origin: Optional[str] = None,
        delegation_depth: Optional[int] = None,
        agent_preset: Optional[str] = None,
    ):
        self.version = version
        self.id = SessionId(session_id)
        self.created_at = created_at if created_at is not None else int(time.time() * 1000)
        self.cwd = cwd
        self.parent_session = parent_session
        self.seed_length = seed_length
        self.origin = origin
        self.delegation_depth = delegation_depth
        self.agent_preset = agent_preset

    @property
    def createdAt(self) -> int:
        return self.created_at

    @property
    def parentSession(self) -> Optional[str]:
        return self.parent_session

    @property
    def seedLength(self) -> Optional[int]:
        return self.seed_length

    @property
    def delegationDepth(self) -> Optional[int]:
        return self.delegation_depth

    @property
    def agentPreset(self) -> Optional[str]:
        return self.agent_preset

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "version": self.version,
            "id": self.id,
            "createdAt": self.created_at,
        }
        if self.cwd is not None:
            result["cwd"] = self.cwd
        if self.parent_session is not None:
            result["parentSession"] = self.parent_session
        if self.seed_length is not None:
            result["seedLength"] = self.seed_length
        if self.origin is not None:
            result["origin"] = self.origin
        if self.delegation_depth is not None:
            result["delegationDepth"] = self.delegation_depth
        if self.agent_preset is not None:
            result["agentPreset"] = self.agent_preset
        return result

    # Mapping protocol methods for dict compatibility
    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        if key in d:
            return d[key]
        if key == "created_at":
            return self.created_at
        if key == "parent_session":
            return self.parent_session
        if key == "seed_length":
            return self.seed_length
        if key == "delegation_depth":
            return self.delegation_depth
        if key == "agent_preset":
            return self.agent_preset
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()

    def keys(self) -> Any:
        return self.to_dict().keys()

    def values(self) -> Any:
        return self.to_dict().values()

    def items(self) -> Any:
        return self.to_dict().items()

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, SessionHeader):
            return self.to_dict() == other.to_dict()
        if isinstance(other, dict):
            return self.to_dict() == other
        return False

    def __repr__(self) -> str:
        return f"SessionHeader({self.to_dict()})"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionHeader":
        """
        Materialize a store-shaped header record (reference index.ts:875-885)
        from a partial metadata mapping, then validate it.

        Port-only convenience: the reference store is the only thing that
        builds a header and it always fills `version`/`id`/`createdAt` itself.
        This helper does the same instead of loosening
        {@link validate_session_header}, which stays exactly as strict as the
        reference validator.
        """
        record = dict(data)
        sid = str(record.get("id", "default-session"))
        record.setdefault("version", SESSION_FORMAT_VERSION)
        record.setdefault("id", sid)
        if record.get("createdAt") is None:
            record["createdAt"] = int(time.time() * 1000)
        return validate_session_header(sid, record)


def _is_safe_int(val: Any) -> bool:
    """`Number.isSafeInteger(val)` for the value kinds a JSON number can hold."""
    return isinstance(val, int) and not isinstance(val, bool) and -0x1FFFFFFFFFFFFF <= val <= 0x1FFFFFFFFFFFFF


def _is_safe_non_negative_int(val: Any) -> bool:
    return _is_safe_int(val) and val >= 0


def _has_provider_model(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    p = obj.get("provider")
    m = obj.get("model")
    return isinstance(p, str) and len(p) > 0 and isinstance(m, str) and len(m) > 0


def assert_session_event_envelope(event: Any, index: Optional[int] = None) -> None:
    subject = f"seed event at index {index}" if index is not None else "session event"
    if not isinstance(event, dict):
        raise ValueError(f"{subject} has an invalid event envelope")

    for k in event.keys():
        if k not in ALLOWED_ENVELOPE_KEYS:
            raise ValueError(f"{subject} has an invalid event envelope")

    etype = event.get("type")
    if not isinstance(etype, str) or len(etype) == 0:
        raise ValueError(f"{subject} has an invalid event envelope")

    if etype == "request/header-delta":
        raise ValueError(f"{subject} uses unsupported legacy request/header-delta format")

    seq = event.get("seq")
    if not _is_safe_non_negative_int(seq):
        raise ValueError(f"{subject} has an invalid event envelope")

    # The reference checks only `Number.isSafeInteger(time)`: a back-dated
    # (negative) clock reading is a legal envelope value, unlike `seq`.
    ev_time = event.get("time")
    if not _is_safe_int(ev_time):
        raise ValueError(f"{subject} has an invalid event envelope")

    # `undefined` is rejected, a literal JSON `null` is NOT: the reference test
    # `event['data'] === undefined` accepts `data: null` (session.spec.ts
    # `rejects pre-provider request headers ... on seed/load` adopts a
    # `plugin/event` seed whose data is null verbatim).
    if "data" not in event:
        raise ValueError(f"{subject} has an invalid event envelope")


def assert_adapter_defaults(defaults: Any, config: Any, index: Optional[int] = None) -> None:
    subject = f"seed request/header at index {index}" if index is not None else "request/header"
    # Only an ABSENT marker returns early; the reference `value === undefined`
    # check exists precisely so that a durable `null` marker is rejected as
    # "invalid adapterDefaults" instead of passing as "no markers".
    if defaults is UNDEFINED:
        return
    if not isinstance(defaults, dict) or isinstance(defaults, list):
        raise ValueError(f"{subject} has invalid adapterDefaults")

    for k, v in defaults.items():
        if k not in ALLOWED_ADAPTER_DEFAULTS or v is not True:
            raise ValueError(f"{subject} has invalid adapterDefaults")
        if not isinstance(config, dict) or k not in config:
            raise ValueError(f"{subject} has invalid adapterDefaults")


def assert_message_event_shape(event: Dict[str, Any], subject: str) -> None:
    etype = event.get("type")
    data = event.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{subject} lacks an identified message")

    if etype == "user/message":
        # A `user/message` carries the message INLINE: the reference reads
        # `const message = type === 'user/message' ? record : record?.['message']`,
        # so a nested `data.message` is never consulted for this type.
        msg = data
        msg_id = msg.get("id")
        if not isinstance(msg_id, str) or len(msg_id) == 0:
            raise ValueError(f"{subject} lacks an identified message")
        role = msg.get("role")
        if role != "user":
            raise ValueError(f'{subject} message must have role "user"')
        source = msg.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("kind"), str) or len(source.get("kind")) == 0:
            raise ValueError(f"{subject} message has invalid source")
        content = msg.get("content")
        if not isinstance(content, list):
            raise ValueError(f"{subject} message has invalid content")

    elif etype == "assistant/message":
        msg = data.get("message") if isinstance(data.get("message"), dict) else data
        msg_id = msg.get("id")
        if not isinstance(msg_id, str) or len(msg_id) == 0:
            raise ValueError(f"{subject} lacks an identified message")
        role = msg.get("role")
        if role != "assistant":
            raise ValueError(f'{subject} message must have role "assistant"')
        source = msg.get("source")
        if not isinstance(source, dict) or source.get("kind") != "model" or not _has_provider_model(source):
            raise ValueError(f"{subject} message must have model source")
        content = msg.get("content")
        if not isinstance(content, list):
            raise ValueError(f"{subject} message has invalid content")

    elif etype == "tool/result":
        msg = data.get("message") if isinstance(data.get("message"), dict) else data
        msg_id = msg.get("id")
        if not isinstance(msg_id, str) or len(msg_id) == 0:
            raise ValueError(f"{subject} lacks an identified message")
        role = msg.get("role")
        if role != "user":
            raise ValueError(f'{subject} message must have role "user"')
        source = msg.get("source")
        if (
            not isinstance(source, dict)
            or source.get("kind") != "tool"
            or not isinstance(source.get("callId"), str)
            or len(source.get("callId")) == 0
        ):
            raise ValueError(f"{subject} message must have tool source")
        content = msg.get("content")
        if not isinstance(content, list):
            raise ValueError(f"{subject} message has invalid content")
        if (
            len(content) != 1
            or not isinstance(content[0], dict)
            or content[0].get("type") != "tool-result"
            or not isinstance(content[0].get("content"), list)
        ):
            raise ValueError(f"{subject} message must contain one tool-result block")
        if content[0].get("toolCallId") != source.get("callId"):
            raise ValueError(f"{subject} message has mismatched tool call ids")


def assert_current_llm_shape(event: Dict[str, Any], index: Optional[int] = None) -> None:
    etype = event.get("type")
    data = event.get("data", {})
    if etype == "request/header":
        subject = f"seed request/header at index {index}" if index is not None else "request/header"
        if not isinstance(data, dict):
            raise ValueError(f"{subject} lacks provider/model")
        hdr = data.get("header")
        if not isinstance(hdr, dict):
            raise ValueError(f"{subject} lacks provider/model")
        config = hdr.get("config")
        if not _has_provider_model(config):
            raise ValueError(f"{subject} lacks provider/model")
        if isinstance(config, dict) and "reasoningEffort" in config:
            re = config["reasoningEffort"]
            if not isinstance(re, str) or len(re) == 0:
                raise ValueError(f"{subject} has an invalid reasoningEffort")
        if "adapterDefaults" in hdr:
            assert_adapter_defaults(hdr["adapterDefaults"], config, index=index)
    elif etype in ("user/message", "assistant/message", "tool/result"):
        subject = (
            f"seed {etype} at index {index}" if index is not None else f"session event at seq {event.get('seq')}"
        )
        assert_message_event_shape(event, subject)


def assert_supported_request_header(etype: str, data: Any, location: str = "request/header") -> None:
    if etype == "request/header-delta":
        raise ValueError(f"{location} uses unsupported legacy request/header-delta format")
    if etype == "request/header" and isinstance(data, dict) and data.get("reason") == "fallback":
        raise ValueError(f'{location} uses unsupported legacy request/header reason "fallback"')


def _js_string(value: Any) -> str:
    """`String(value)` for the value kinds a header field can hold."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return value
    if type(value) is float and value.is_integer():
        return str(int(value))
    return str(value)


def validate_session_header(session_id: str, input_data: Any) -> SessionHeader:
    """
    Validate one detached session header, 1:1 with reference
    `validateSessionHeader` (index.ts:96-136):

    - `version`, `id` and `createdAt` are REQUIRED. The reference compares the
      read value against the expected one, so an omitted field is a mismatch
      (`String(undefined)` is rendered in the message), never a default.
    - only the canonical camelCase keys are read: snake_case aliases are not
      part of the storage contract and are ignored.
    - an explicitly supplied `null` for an optional field is a type error
      (`typeof null !== 'string'`), so "omitted" is tracked with the
      `undefined` sentinel rather than with `None`.
    - `seedLength`/`delegationDepth` are validated BEFORE any numeric
      conversion, so `"1"`, `0.5` and `-1` are rejected rather than coerced.
    """
    if isinstance(input_data, SessionHeader):
        input_data = input_data.to_dict()
    if input_data is None or not isinstance(input_data, dict):
        raise ValueError("session header is not a plain JSON record")

    raw_version = input_data.get("version", UNDEFINED)
    if type(raw_version) is not int or raw_version != SESSION_FORMAT_VERSION:
        raise ValueError(
            f"session header version must be {SESSION_FORMAT_VERSION}, got {_js_string(raw_version)}"
        )

    raw_id = input_data.get("id", UNDEFINED)
    if raw_id != session_id:
        raise ValueError(
            f'session header id "{_js_string(raw_id)}" does not match session id "{session_id}"'
        )

    raw_created = input_data.get("createdAt", UNDEFINED)
    if not _is_safe_non_negative_int(raw_created):
        raise ValueError("session header createdAt must be a non-negative safe integer")
    created_at: int = raw_created

    cwd: Optional[str] = None
    raw_cwd = input_data.get("cwd", UNDEFINED)
    if raw_cwd is not UNDEFINED:
        if not isinstance(raw_cwd, str):
            raise ValueError("session header cwd must be a string")
        if not os.path.isabs(raw_cwd):
            raise ValueError(f'session header cwd must be an absolute path, got "{raw_cwd}"')
        cwd = raw_cwd

    parent_session: Optional[str] = None
    raw_parent = input_data.get("parentSession", UNDEFINED)
    if raw_parent is not UNDEFINED:
        if not isinstance(raw_parent, str):
            raise ValueError("session header parentSession must be a string")
        parent_session = raw_parent

    seed_length: Optional[int] = None
    raw_seed_len = input_data.get("seedLength", UNDEFINED)
    if raw_seed_len is not UNDEFINED:
        if not _is_safe_non_negative_int(raw_seed_len):
            raise ValueError("session header seedLength must be a non-negative safe integer")
        seed_length = raw_seed_len

    origin: Optional[str] = None
    raw_origin = input_data.get("origin", UNDEFINED)
    if raw_origin is not UNDEFINED:
        if raw_origin != "subagent":
            raise ValueError('session header origin must be "subagent"')
        origin = raw_origin

    delegation_depth: Optional[int] = None
    raw_depth = input_data.get("delegationDepth", UNDEFINED)
    if raw_depth is not UNDEFINED:
        if not _is_safe_non_negative_int(raw_depth):
            raise ValueError("session header delegationDepth must be a non-negative safe integer")
        delegation_depth = raw_depth

    agent_preset: Optional[str] = None
    raw_preset = input_data.get("agentPreset", UNDEFINED)
    if raw_preset is not UNDEFINED:
        if not isinstance(raw_preset, str):
            raise ValueError("session header agentPreset must be a string")
        agent_preset = raw_preset

    return SessionHeader(
        session_id=session_id,
        version=raw_version,
        created_at=created_at,
        cwd=cwd,
        parent_session=parent_session,
        seed_length=seed_length,
        origin=origin,
        delegation_depth=delegation_depth,
        agent_preset=agent_preset,
    )


def validate_restored_session_header(session_id: str, input_data: Any) -> SessionHeader:
    """Validate exclusively owned persistence header."""
    return validate_session_header(session_id, input_data)


def snapshot_session_header(session_id: str, source: Any = UNDEFINED) -> SessionHeader:
    """
    Detach, validate, and freeze creation metadata published by a session.

    `source` distinguishes an omitted header (the `undefined` overload slot, which
    receives the minimal current-version default) from an explicit non-record such
    as `None`/`1`, which the header validator rejects as "not a plain JSON
    record", exactly like reference `snapshotSessionHeader(id, source)`.
    """
    if isinstance(source, SessionHeader):
        source = source.to_dict()
    raw: Any = (
        {"version": SESSION_FORMAT_VERSION, "id": session_id, "createdAt": int(time.time() * 1000)}
        if source is UNDEFINED
        else source
    )
    # A JSON `null` is a VALID snapshot payload, so the invalid-payload signal
    # must be the detach sentinel itself rather than `None`.
    snap = walk_json_value(raw, detach=True, undefined_sentinel=UNDEFINED)
    if snap is UNDEFINED:
        raise ValueError("session header is not losslessly JSON-serializable")
    return validate_session_header(session_id, snap)


def adopt_session_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate an exclusively owned event and deeply freeze its identified message
    without copying the event, 1:1 with reference `adoptSessionEvent`
    (index.ts:167-185): a `user/message` freezes its whole `data`, while
    `assistant/message` and `tool/result` freeze the identified `data.message`
    and leave `usage`/`timing`/`meta` untouched.
    """
    assert_session_event_envelope(event)
    assert_current_llm_shape(event)
    etype = event.get("type")
    data = event.get("data")
    if type(data) is dict:
        if etype == "user/message":
            event["data"] = deep_freeze(data)
        elif etype in ("assistant/message", "tool/result"):
            message = data.get("message")
            if type(message) is dict:
                data["message"] = deep_freeze(message)
    return event


def snapshot_session_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a detached, deeply frozen event snapshot, 1:1 with reference
    `snapshotSessionEvent` (index.ts:192-194): a JSON-materializing detach
    (`structuredClone`) followed by {@link adopt_session_event}.
    """
    assert_session_event_envelope(event)
    snap = snapshot_json_value(event)
    if snap is None:
        raise TypeError("event is not losslessly JSON-serializable")
    return adopt_session_event(snap)


# CamelCase aliases 1:1 with reference
adoptSessionEvent = adopt_session_event
snapshotSessionEvent = snapshot_session_event

