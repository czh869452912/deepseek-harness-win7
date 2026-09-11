"""
Pure ACP transcript and session-log normalizers.
Ported 1:1 from reference packages/test-support/session-snapshot/src/normalize.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from .chunk_rows import decode_storage_record, pack_chunk_runs
from .identity import redact_session_snapshot_ids
from .seq_ranges import decode_seq_ranges

SESSION_ID = "{{sessionId}}"
MESSAGE_ID = "{{messageId}}"
USED_TOKENS = "{{usedTokens}}"
CWD = "{{cwd}}"
SYSTEM = "{{system}}"
TOOLS = "{{tools}}"
EVENT_TIME = "{{eventTime}}"
EVENT_OMITTED_BYTES = "{{eventOmittedBytes}}"
PACKED_CHUNK_ROW_TYPES = {"text-chunks", "reasoning-chunks", "tool-call-chunks"}


def _is_packed_fixture_row(record: Dict[str, Any]) -> bool:
    return isinstance(record, dict) and record.get("type") in PACKED_CHUNK_ROW_TYPES


def _omit_fixture_envelope(record: Dict[str, Any]) -> None:
    record.pop("seq", None)
    record.pop("time", None)
    record.pop("seq0", None)
    record.pop("time0", None)


CWD_ROOTED_PATH_RE = re.compile(r"\{\{cwd\}\}(?:[\\/][^\s<>'\"`]+)+")
PATH_TAG_RE = re.compile(r"(<path>)([^<]*)(</path>)")
ADDITIONAL_INSTRUCTIONS_PATH_RE = re.compile(r"(Additional instructions from: )([^\r\n]+)")
EMBEDDED_EVENT_TIME_RE = re.compile(r'^(  "time": )\d+(?=,\r?$)', re.MULTILINE)
EVENT_READ_OMITTED_BYTES_RE = re.compile(r"(\r?\n\r?\n\(Omitted )\d+( bytes\.)")
EVENT_READ_TARGET_REGION_RE = re.compile(
    r"^Session [^\r\n]+ [—\-] [^\r\n]+\r?\nTarget event seq \d+:\r?\n```json\r?\n\{\r?\n[\s\S]*?(?=\r?\n```(?:\r?\n|$)|\r?\n\r?\n\(Omitted )",
    re.MULTILINE,
)
PATH_TEXT_BOUNDARY_RE = re.compile(r"[\s<>'\"`()\[\]{},;:!?=]")
FILE_URI_PATH_PREFIX_RE = re.compile(r"(?:^|[^a-z0-9+.-])file:///?$", re.IGNORECASE)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

LOCAL_SPILL_PATH_RE = re.compile(
    r"\{\{cwd\}\}[\\/]\.spill[\\/]session-[0-9a-f]{12}[\\/][0-9a-f]{12}-([A-Za-z0-9._~-]+?)(?=\. Use read with offset/limit|[\s)]|$)"
)
SNAPSHOT_SPILL_PATH_RE = re.compile(
    r"(?:[A-Za-z]:)?[\\/](?:tmp|t)[\\/](?:dsh-acp-snap-[0-9a-f]{9}|dsh-acp-snapshot-spill)[\\/]session-[0-9a-f]{12}[\\/][0-9a-f]{12}-([A-Za-z0-9._~-]+?)(?=\. Use read with offset/limit|[\s)]|$)"
)


class NormalizeContext:
    def __init__(
        self,
        sessionIds: Optional[Sequence[str]] = None,
        cwd: str = "",
        cwdAliases: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ):
        raw_sids = sessionIds if sessionIds is not None else kwargs.get("session_ids") or []
        self.sessionIds: List[str] = list(raw_sids)
        self.cwd: str = cwd if cwd else kwargs.get("cwd", "")
        raw_aliases = cwdAliases if cwdAliases is not None else kwargs.get("cwd_aliases") or []
        self.cwdAliases: List[str] = list(raw_aliases)


def _coerce_ctx(ctx: Any) -> NormalizeContext:
    if isinstance(ctx, NormalizeContext):
        return ctx
    if isinstance(ctx, dict):
        return NormalizeContext(
            sessionIds=ctx.get("sessionIds") if "sessionIds" in ctx else ctx.get("session_ids", []),
            cwd=ctx.get("cwd", ""),
            cwdAliases=ctx.get("cwdAliases") if "cwdAliases" in ctx else ctx.get("cwd_aliases", []),
        )
    return NormalizeContext(
        sessionIds=getattr(ctx, "sessionIds", getattr(ctx, "session_ids", [])),
        cwd=getattr(ctx, "cwd", ""),
        cwdAliases=getattr(ctx, "cwdAliases", getattr(ctx, "cwd_aliases", [])),
    )


def extract_snapshot_spill_paths(content: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for m in SNAPSHOT_SPILL_PATH_RE.finditer(content):
        name = m.group(1)
        if name:
            result[name] = m.group(0)
    return result


def _canonicalize_embedded_paths(value: str) -> str:
    v = PATH_TAG_RE.sub(lambda m: f"{m.group(1)}{m.group(2).replace(chr(92), '/')}{m.group(3)}", value)
    v = ADDITIONAL_INSTRUCTIONS_PATH_RE.sub(lambda m: f"{m.group(1)}{m.group(2).replace(chr(92), '/')}", v)
    return v


def _cwd_spellings(ctx: NormalizeContext) -> List[str]:
    base_spellings = [ctx.cwd] + ctx.cwdAliases
    seen: Set[str] = set()
    spellings: List[str] = []
    for s in base_spellings:
        if s and s not in seen:
            seen.add(s)
            spellings.append(s)

    mac_aliases: List[str] = []
    for s in spellings:
        if s.startswith("/") and not s.startswith("/private/"):
            mac_aliases.append(f"/private{s}")

    all_spellings = spellings + [m for m in mac_aliases if m not in seen]
    all_spellings.sort(key=lambda x: len(x), reverse=True)
    return all_spellings


def _is_cwd_match(value: str, start: int, length: int) -> bool:
    before = value[start - 1] if start > 0 else None
    after_idx = start + length
    after = value[after_idx] if after_idx < len(value) else None
    after_punct = value[after_idx + 1] if after_idx + 1 < len(value) else None

    starts_at_boundary = (
        before is None
        or bool(PATH_TEXT_BOUNDARY_RE.match(before))
        or bool(FILE_URI_PATH_PREFIX_RE.search(value[:start]))
    )
    ends_at_boundary = (
        after is None
        or after == "/"
        or after == "\\"
        or bool(PATH_TEXT_BOUNDARY_RE.match(after))
        or (after == "." and (after_punct is None or bool(PATH_TEXT_BOUNDARY_RE.match(after_punct))))
    )
    return starts_at_boundary and ends_at_boundary


def _replace_cwd_spelling(value: str, spelling: str, replacement: str) -> str:
    cursor = 0
    out = ""
    val_len = len(value)
    sp_len = len(spelling)
    while cursor < val_len:
        match_idx = value.find(spelling, cursor)
        if match_idx < 0:
            return out + value[cursor:]
        end = match_idx + sp_len
        if _is_cwd_match(value, match_idx, sp_len):
            out += value[cursor:match_idx] + replacement
        else:
            out += value[cursor:end]
        cursor = end
    return out


def _replace_cwd(value: str, ctx: NormalizeContext, replacement: str) -> str:
    out = value
    for sp in _cwd_spellings(ctx):
        out = _replace_cwd_spelling(out, sp, replacement)
    return out


def _scrub_string(
    value: str,
    ctx: NormalizeContext,
    cwd_path_mode: str,
    identity_mode: str,
) -> str:
    out = _replace_cwd(value, ctx, CWD)
    out = out.replace(f"/private{CWD}", CWD)
    if cwd_path_mode == "canonical":
        out = CWD_ROOTED_PATH_RE.sub(lambda m: m.group(0).replace("\\", "/"), out)
        out = _canonicalize_embedded_paths(out)
    out = LOCAL_SPILL_PATH_RE.sub(lambda m: f"{{{{spillLocator:{m.group(1)}}}}}", out)
    out = SNAPSHOT_SPILL_PATH_RE.sub(lambda m: f"{{{{spillLocator:{m.group(1)}}}}}", out)

    if EVENT_READ_TARGET_REGION_RE.search(out):
        def _replace_region(target_m):
            target_str = target_m.group(0)
            target_str = EMBEDDED_EVENT_TIME_RE.sub(rf"\g<1>{EVENT_TIME}", target_str)
            return target_str

        out = EVENT_READ_TARGET_REGION_RE.sub(_replace_region, out)
        out = EVENT_READ_OMITTED_BYTES_RE.sub(rf"\g<1>{EVENT_OMITTED_BYTES}\g<2>", out)

    if identity_mode == "legacy":
        for sid in ctx.sessionIds:
            out = out.replace(sid, SESSION_ID)
        out = UUID_RE.sub(SESSION_ID, out)
    return out


def _scrub_value(
    value: Any,
    ctx: NormalizeContext,
    cwd_path_mode: str,
    identity_mode: str,
    key: Optional[str] = None,
) -> Any:
    if isinstance(value, str):
        if identity_mode == "legacy" and key == "messageId":
            return MESSAGE_ID
        scrubbed = _scrub_string(value, ctx, cwd_path_mode, identity_mode)
        return scrubbed.replace("\\", "/") if (cwd_path_mode == "canonical" and key == "path") else scrubbed
    if isinstance(value, list):
        return [_scrub_value(v, ctx, cwd_path_mode, identity_mode) for v in value]
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            out[k] = _scrub_value(v, ctx, cwd_path_mode, identity_mode, k)
        if value.get("sessionUpdate") == "usage_update" and isinstance(value.get("used"), (int, float)):
            out["used"] = USED_TOKENS
        return out
    return value


def _tokenize_fixture_string(value: str, ctx: NormalizeContext, basename: str) -> str:
    exact = _replace_cwd(value, ctx, CWD)
    escaped_base = re.escape(basename)
    abs_cwd_re = re.compile(
        rf"(?:[A-Za-z]:)?[\\/](?:[^\\/\s<>\"']+[\\/])*{escaped_base}(?=$|[\\/\s<>'\"`()\[\]{{}},;:!?=])"
    )
    return abs_cwd_re.sub(CWD, exact).replace(f"/private{CWD}", CWD)


def _tokenize_fixture_value(value: Any, ctx: NormalizeContext, basename: str) -> Any:
    if isinstance(value, str):
        return _tokenize_fixture_string(value, ctx, basename)
    if isinstance(value, list):
        return [_tokenize_fixture_value(item, ctx, basename) for item in value]
    if isinstance(value, dict):
        return {k: _tokenize_fixture_value(v, ctx, basename) for k, v in value.items()}
    return value


def tokenize_session_fixture_cwd(raw_log: str) -> str:
    lines = raw_log.split("\n")
    first_line = next((line for line in lines if line.strip()), None)
    header = json.loads(first_line) if first_line else None
    cwd = header.get("cwd", "") if isinstance(header, dict) else ""
    basename = os.path.basename(cwd.replace("\\", "/"))
    if not basename:
        raise ValueError("acp-snapshot: cannot tokenize a cwd without a basename")
    ctx = NormalizeContext(sessionIds=[], cwd=cwd)
    res_lines = []
    for line in lines:
        if not line.strip():
            res_lines.append(line)
        else:
            tokenized = _tokenize_fixture_value(json.loads(line), ctx, basename)
            res_lines.append(json.dumps(tokenized, separators=(",", ":")))
    return "\n".join(res_lines)


def normalize_stdout(
    raw_stdout: str,
    ctx: Union[NormalizeContext, Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
) -> str:
    c = _coerce_ctx(ctx)
    opts = options or {}
    cwd_path_mode = opts.get("cwdPathMode", "canonical")
    identity_mode = opts.get("identityMode", "legacy")
    lines = [line for line in raw_stdout.split("\n") if line.strip()]

    id_seq: Dict[str, int] = {}

    def stable_id(val: Any) -> int:
        k = json.dumps(val, separators=(",", ":"))
        if k not in id_seq:
            id_seq[k] = len(id_seq) + 1
        return id_seq[k]

    frames = []
    for line in lines:
        frame = json.loads(line)
        if "id" in frame and frame["id"] is not None:
            frame["id"] = stable_id(frame["id"])
        frames.append(_scrub_value(frame, c, cwd_path_mode, identity_mode))
    return "\n".join(json.dumps(f, separators=(",", ":")) for f in frames) + "\n"


def normalize_session_log(
    raw_log: str,
    ctx: Union[NormalizeContext, Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
) -> str:
    c = _coerce_ctx(ctx)
    opts = options or {}
    cwd_path_mode = opts.get("cwdPathMode", "canonical")
    identity_mode = opts.get("identityMode", "legacy")
    lines = [line for line in raw_log.split("\n") if line.strip()]
    records = []
    for line in lines:
        record = json.loads(line)
        r_type = record.get("type")
        if r_type == "session":
            if "createdAt" in record:
                record["createdAt"] = 0
        elif _is_packed_fixture_row(record):
            if "time0" in record:
                record["time0"] = 0
            data = record.get("data")
            if isinstance(data, dict) and isinstance(data.get("dt"), list):
                data["dt"] = [0 for _ in data["dt"]]
        elif "time" in record:
            record["time"] = 0

        if r_type == "hook/result" and isinstance(record.get("data"), dict):
            if "durationMs" in record["data"]:
                record["data"]["durationMs"] = 0
        if r_type == "goal/change" and isinstance(record.get("data"), dict):
            if "createdAt" in record["data"]:
                record["data"]["createdAt"] = 0
            if "updatedAt" in record["data"]:
                record["data"]["updatedAt"] = 0
        if "sourceEventSeqs" in record:
            record["sourceEventSeqs"] = decode_seq_ranges(record["sourceEventSeqs"])
        records.append(_scrub_value(record, c, cwd_path_mode, identity_mode))
    return "\n".join(json.dumps(r, separators=(",", ":")) for r in records) + "\n"


def _repack_session_snapshot(raw_log: str) -> str:
    lines = [line for line in raw_log.split("\n") if line.strip()]
    if not lines:
        return ""
    header = lines[0]
    lines = lines[1:]

    next_seq = 0
    events: List[Dict[str, Any]] = []
    for line in lines:
        record = json.loads(line)
        if _is_packed_fixture_row(record):
            rec_copy = dict(record)
            rec_copy["seq0"] = next_seq
            rec_copy["time0"] = 0
            decoded = decode_storage_record(rec_copy)
            next_seq += len(decoded)
            events.extend(decoded)
        else:
            record["seq"] = next_seq
            record["time"] = 0
            next_seq += 1
            events.append(record)

    packed = pack_chunk_runs(events)
    body: List[str] = []
    for stored in packed:
        projected = dict(stored)
        _omit_fixture_envelope(projected)
        body.append(json.dumps(projected, separators=(",", ":")))
    return "\n".join([header] + body) + "\n"


def _scrub_header_content(raw_log: str, system: bool = False, tools: bool = False) -> str:
    lines = raw_log.split("\n")
    out: List[str] = []
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        record = json.loads(line)
        data = record.get("data")
        if not isinstance(data, dict):
            out.append(line)
            continue
        if record.get("type") == "request/header":
            header = data.get("header")
            if isinstance(header, dict):
                touched = False
                if system and "system" in header:
                    header["system"] = SYSTEM
                    touched = True
                if tools and "tools" in header:
                    header["tools"] = TOOLS
                    touched = True
                if touched:
                    out.append(json.dumps(record, separators=(",", ":")))
                    continue
        out.append(line)
    return "\n".join(out)


def scrub_system_prompts(raw_log: str) -> str:
    return _scrub_header_content(raw_log, system=True)


def scrub_tool_schemas(raw_log: str) -> str:
    return _scrub_header_content(raw_log, tools=True)


def scrub_request_headers(raw_log: str) -> str:
    return _scrub_header_content(raw_log, system=True, tools=True)


def scrub_session_snapshot(raw_log: str) -> str:
    scrubbed = scrub_request_headers(raw_log)
    lines = scrubbed.split("\n")
    record_index = 0
    res: List[str] = []
    for line in lines:
        if not line.strip():
            res.append(line)
            continue
        record = json.loads(line)
        if record_index == 0:
            if record.get("type") != "session":
                raise ValueError("session snapshot must start with a session header")
            record_index += 1
            res.append(line)
            continue
        record_index += 1
        _omit_fixture_envelope(record)
        res.append(json.dumps(record, separators=(",", ":")))
    return "\n".join(res)


def normalize_session_snapshot(
    raw_log: str,
    ctx: Union[NormalizeContext, Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
) -> str:
    c = _coerce_ctx(ctx)
    return _repack_session_snapshot(scrub_session_snapshot(normalize_session_log(raw_log, c, options)))


def normalize_session_snapshots(
    raw_logs: Sequence[str],
    ctx: Union[NormalizeContext, Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
) -> List[str]:
    c = _coerce_ctx(ctx)
    opts = dict(options or {})
    redacted_logs = redact_session_snapshot_ids(raw_logs)
    out: List[str] = []
    for log in redacted_logs:
        sub_ctx = NormalizeContext(sessionIds=[], cwd=c.cwd, cwdAliases=c.cwdAliases)
        sub_opts = dict(opts)
        sub_opts["identityMode"] = "preserve"
        out.append(_repack_session_snapshot(scrub_session_snapshot(normalize_session_log(log, sub_ctx, sub_opts))))
    return out


extractSnapshotSpillPaths = extract_snapshot_spill_paths
tokenizeSessionFixtureCwd = tokenize_session_fixture_cwd
normalizeStdout = normalize_stdout
normalizeSessionLog = normalize_session_log
normalizeSessionSnapshot = normalize_session_snapshot
normalizeSessionSnapshots = normalize_session_snapshots
scrubSystemPrompts = scrub_system_prompts
scrubToolSchemas = scrub_tool_schemas
scrubRequestHeaders = scrub_request_headers
scrubSessionSnapshot = scrub_session_snapshot
