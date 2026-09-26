"""
Durable storage-domain declaration for lifecycle-bound message feedback.
Aligned 1:1 with official `@deepseek-ai/dsh-message-feedback/src/spec`.
"""

import re
from typing import Any, Dict, List

from dsh.storage.domain_spec import SchemaValidator, define_domain, domain_table

# Largest integer JavaScript represents exactly (`Number.MAX_SAFE_INTEGER`).
MAX_SAFE_INTEGER = 0x1FFFFFFFFFFFFF

# RFC 4122 UUID text form (`z.uuid()`).
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

RATINGS = ("positive", "negative")


def _require_non_negative_safe_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be a non-negative safe integer" % field)
    if value < 0 or value > MAX_SAFE_INTEGER:
        raise ValueError("%s must be a non-negative safe integer" % field)
    return value


def parse_message_feedback_rating(value: Any) -> str:
    """Runtime schema for the closed rating vocabulary."""
    if value not in RATINGS:
        raise ValueError("message feedback rating must be 'positive' or 'negative'")
    return value


def parse_message_feedback_version(value: Any) -> str:
    """Runtime schema for one opaque item version stored on disk."""
    if not isinstance(value, str) or not UUID_RE.match(value):
        raise ValueError("message feedback version must be a UUID")
    return value


def parse_message_feedback_item(data: Any) -> Dict[str, Any]:
    """Runtime schema for one current feedback item."""
    if not isinstance(data, dict):
        raise ValueError("message feedback item must be an object")
    message_id = data.get("messageId")
    if not isinstance(message_id, str) or len(message_id) < 1:
        raise ValueError("message feedback messageId must be a non-empty string")
    rating = parse_message_feedback_rating(data.get("rating"))
    item: Dict[str, Any] = {"messageId": message_id, "rating": rating}
    note = data.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise ValueError("message feedback note must be a string")
        if len(note.strip()) == 0:
            raise ValueError("message feedback note must contain a non-whitespace character")
        item["note"] = note
    version = parse_message_feedback_version(data.get("version"))
    created_at = _require_non_negative_safe_integer(data.get("createdAt"), "message feedback createdAt")
    updated_at = _require_non_negative_safe_integer(data.get("updatedAt"), "message feedback updatedAt")
    if updated_at < created_at:
        raise ValueError("message feedback updatedAt must not precede createdAt")
    item["version"] = version
    item["createdAt"] = created_at
    item["updatedAt"] = updated_at
    return item


def parse_message_feedback_session_identity(data: Any) -> Dict[str, Any]:
    """Persisted Session fields that fence a sidecar row to one log lifecycle."""
    if not isinstance(data, dict):
        raise ValueError("message feedback session identity must be an object")
    identity: Dict[str, Any] = {
        "createdAt": _require_non_negative_safe_integer(
            data.get("createdAt"), "message feedback session createdAt"
        )
    }
    cwd = data.get("cwd")
    if cwd is not None:
        if not isinstance(cwd, str):
            raise ValueError("message feedback session cwd must be a string")
        identity["cwd"] = cwd
    return identity


def parse_message_feedback_row(data: Any) -> Dict[str, Any]:
    """
    One whole-Session sidecar. Duplicate message ids would make item lookup
    ambiguous; duplicate versions would break their independent identity.
    """
    if not isinstance(data, dict):
        raise ValueError("message feedback row must be an object")
    session = parse_message_feedback_session_identity(data.get("session"))
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("message feedback row items must be an array")
    items: List[Dict[str, Any]] = []
    message_ids = set()
    versions = set()
    for index, raw in enumerate(raw_items):
        item = parse_message_feedback_item(raw)
        if item["messageId"] in message_ids:
            raise ValueError("duplicate message feedback id '%s'" % item["messageId"])
        message_ids.add(item["messageId"])
        if item["version"] in versions:
            raise ValueError("duplicate message feedback version '%s'" % item["version"])
        versions.add(item["version"])
        items.append(item)
    return {"session": session, "items": items}


message_feedback_rating_schema = SchemaValidator(parse_message_feedback_rating)
messageFeedbackRatingSchema = message_feedback_rating_schema

message_feedback_version_schema = SchemaValidator(parse_message_feedback_version)
messageFeedbackVersionSchema = message_feedback_version_schema

message_feedback_item_schema = SchemaValidator(parse_message_feedback_item)
messageFeedbackItemSchema = message_feedback_item_schema

message_feedback_session_identity_schema = SchemaValidator(parse_message_feedback_session_identity)
messageFeedbackSessionIdentitySchema = message_feedback_session_identity_schema

message_feedback_row_schema = SchemaValidator(parse_message_feedback_row)
messageFeedbackRowSchema = message_feedback_row_schema


#: One lifecycle-bound sidecar record per Session id.
message_feedback_domain_spec = define_domain(
    name="message_feedback",
    version=0,
    tables={"sessions": domain_table(message_feedback_row_schema)},
)

messageFeedbackDomainSpec = message_feedback_domain_spec

__all__ = [
    "RATINGS",
    "UUID_RE",
    "message_feedback_domain_spec",
    "messageFeedbackDomainSpec",
    "message_feedback_item_schema",
    "messageFeedbackItemSchema",
    "message_feedback_rating_schema",
    "messageFeedbackRatingSchema",
    "message_feedback_row_schema",
    "messageFeedbackRowSchema",
    "message_feedback_session_identity_schema",
    "messageFeedbackSessionIdentitySchema",
    "message_feedback_version_schema",
    "messageFeedbackVersionSchema",
    "parse_message_feedback_item",
    "parse_message_feedback_rating",
    "parse_message_feedback_row",
    "parse_message_feedback_session_identity",
    "parse_message_feedback_version",
]
