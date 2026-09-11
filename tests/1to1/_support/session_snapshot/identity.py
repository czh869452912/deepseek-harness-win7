"""
Relationship-preserving identity redaction for committed session snapshots.
Ported 1:1 from reference packages/test-support/session-snapshot/src/identity.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

UUID_FRAGMENT_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
LEGACY_TOKEN_RE = re.compile(r"^\{\{(?:sessionId|messageId)\}\}$")
CANONICAL_TOKEN_RE = re.compile(r"^\{\{(session|message|approval|workflow|command|rpc|retry|id):([1-9]\d*)\}\}$")
ID_KEY_RE = re.compile(r"(?:^id$|Id$|Ids$)")
AS_MESSAGE_RE = re.compile(r"\bas message ([0-9a-f-]{36})\b", re.IGNORECASE)
ANONYMOUS_USER_RE = re.compile(r"\bAnonymous user: ([0-9a-f-]{36})\b", re.IGNORECASE)


def _message_id(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    val_id = value.get("id")
    role = value.get("role")
    content = value.get("content")
    source = value.get("source")
    if (
        isinstance(val_id, str)
        and isinstance(role, str)
        and isinstance(content, list)
        and isinstance(source, dict)
    ):
        return val_id
    return None


def _redacted_candidate(value: str) -> bool:
    return bool(
        UUID_FRAGMENT_RE.search(value)
        or LEGACY_TOKEN_RE.search(value)
        or CANONICAL_TOKEN_RE.search(value)
    )


def redact_session_snapshot_ids(logs: Sequence[str]) -> List[str]:
    """
    Replace volatile opaque ids while preserving equality relationships across a parent and its child logs.
    """
    parsed: List[Dict[str, Any]] = []
    for log in logs:
        records = []
        for line in re.split(r"\r?\n", log):
            if line.strip():
                records.append(json.loads(line))
        parsed.append({"records": records, "trailingNewline": log.endswith("\n")})

    token_by_value: Dict[str, str] = {}
    next_by_kind: Dict[str, int] = {}

    def claim(value: Any, kind: str, always: bool = False) -> None:
        if not isinstance(value, str) or not value or value in token_by_value:
            return
        if not always and not _redacted_candidate(value):
            return
        canon_match = CANONICAL_TOKEN_RE.match(value)
        if canon_match:
            canonical_kind = canon_match.group(1)
            ordinal = int(canon_match.group(2))
            next_by_kind[canonical_kind] = max(next_by_kind.get(canonical_kind, 0), ordinal)
            token_by_value[value] = value
            return
        nxt = next_by_kind.get(kind, 0) + 1
        next_by_kind[kind] = nxt
        token_by_value[value] = f"{{{{{kind}:{nxt}}}}}"

    for log_item in parsed:
        if log_item["records"]:
            header = log_item["records"][0]
            if isinstance(header, dict) and header.get("type") == "session":
                claim(header.get("id"), "session", True)

    def collect(value: Any, record_type: Any = None) -> None:
        if isinstance(value, str):
            for m in AS_MESSAGE_RE.finditer(value):
                claim(m.group(1), "message")
            for m in ANONYMOUS_USER_RE.finditer(value):
                claim(m.group(1), "id")
            return
        if isinstance(value, list):
            for item in value:
                collect(item, record_type)
            return
        if not isinstance(value, dict):
            return

        identified_message = _message_id(value)
        if identified_message is not None:
            claim(identified_message, "message")

        for child_key, item in value.items():
            if record_type in ("approval/asked", "approval/decided"):
                if child_key == "id":
                    claim(item, "approval")
            elif child_key == "commandId":
                claim(item, "command", True)
            elif child_key == "rpcId":
                claim(item, "rpc", True)
            elif child_key == "retryId":
                claim(item, "retry")
            elif child_key == "runId":
                claim(item, "workflow")
            elif ID_KEY_RE.search(child_key):
                claim(item, "id")
            collect(item, record_type)

    for log_item in parsed:
        for record in log_item["records"]:
            collect(record, record.get("type") if isinstance(record, dict) else None)

    # Sort replacements by source length descending
    replacements = sorted(token_by_value.items(), key=lambda kv: len(kv[0]), reverse=True)

    def replace(value: Any) -> Any:
        if isinstance(value, str):
            exact = token_by_value.get(value)
            if exact is not None:
                return exact
            output = value
            for source, token in replacements:
                output = output.replace(source, token)
            return output
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {k: replace(v) for k, v in value.items()}
        return value

    out_logs: List[str] = []
    for log_item in parsed:
        lines = [json.dumps(replace(record), separators=(",", ":")) for record in log_item["records"]]
        content = "\n".join(lines)
        if log_item["trailingNewline"]:
            content += "\n"
        out_logs.append(content)
    return out_logs


redactSessionSnapshotIds = redact_session_snapshot_ids
