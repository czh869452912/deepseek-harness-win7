"""
Lossless row packing for assistant/chunk delta runs.
Ported 1:1 from reference packages/core/session/src/chunk-rows.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List, Optional, Sequence, Union

MIN_RUN = 3
MAX_SAFE_INTEGER = 0x1FFFFFFFFFFFFF


def is_chunk_row(record: Dict[str, Any]) -> bool:
    """Test whether an encoded record is a packed chunk row rather than a Session event."""
    if not isinstance(record, dict):
        return False
    t = record.get("type")
    return t in ("text-chunks", "reasoning-chunks", "tool-call-chunks")


def chunk_row_length(row: Dict[str, Any]) -> int:
    """Number of logical Session events represented by one packed row."""
    t = row.get("type")
    data = row.get("data", {})
    if t == "tool-call-chunks":
        return len(data.get("args", []))
    return len(data.get("texts", []))


def _has_exact_keys(d: Dict[str, Any], keys: Sequence[str]) -> bool:
    return len(d) == len(keys) and all(k in d for k in keys)


def _is_number(value: Any) -> bool:
    """JavaScript `typeof value === 'number'`: ints and floats, never bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_safe_integer(value: Any) -> bool:
    """`Number.isSafeInteger`: an integer within +/-(2**53 - 1)."""
    return isinstance(value, int) and not isinstance(value, bool) and abs(value) <= MAX_SAFE_INTEGER


def _classify(event: Dict[str, Any]) -> Optional[str]:
    if not isinstance(event, dict) or event.get("type") != "assistant/chunk":
        return None
    if not _has_exact_keys(event, ["type", "seq", "time", "data"]):
        return None
    seq = event.get("seq")
    time_val = event.get("time")
    if not _is_safe_integer(seq) or seq < 0 or not _is_safe_integer(time_val):
        return None
    data = event.get("data")
    if not isinstance(data, dict) or not _has_exact_keys(data, ["turn", "step", "chunk"]):
        return None
    turn = data.get("turn")
    step = data.get("step")
    chunk = data.get("chunk")
    if not _is_number(turn) or not _is_number(step) or not isinstance(chunk, dict):
        return None
    c_idx = chunk.get("index")
    if not _is_number(c_idx):
        return None
    c_type = chunk.get("type")
    if c_type in ("text-delta", "reasoning-delta"):
        if _has_exact_keys(chunk, ["type", "index", "text"]) and isinstance(chunk.get("text"), str):
            return c_type
        return None
    elif c_type == "tool-call-delta":
        shape_ok = _has_exact_keys(chunk, ["type", "index", "id", "argumentsDelta"]) or (
            _has_exact_keys(chunk, ["type", "index", "id", "name", "argumentsDelta"])
            and isinstance(chunk.get("name"), str)
        )
        if (
            shape_ok
            and isinstance(chunk.get("id"), str)
            and isinstance(chunk.get("argumentsDelta"), str)
        ):
            return c_type
        return None
    return None


def _tool_call_of(event: Dict[str, Any]) -> Dict[str, Any]:
    return event["data"]["chunk"]


def _index_of(event: Dict[str, Any]) -> int:
    return event["data"]["chunk"]["index"]


def _continues(prev: Dict[str, Any], nxt: Dict[str, Any], kind: str) -> bool:
    if nxt["seq"] != prev["seq"] + 1:
        return False
    gap = nxt["time"] - prev["time"]
    if abs(gap) > MAX_SAFE_INTEGER:
        return False
    if nxt["data"]["turn"] != prev["data"]["turn"] or nxt["data"]["step"] != prev["data"]["step"]:
        return False
    if _index_of(nxt) != _index_of(prev):
        return False
    if kind != "tool-call-delta":
        return True
    a = _tool_call_of(prev)
    b = _tool_call_of(nxt)
    return (
        a.get("id") == b.get("id")
        and ("name" in a) == ("name" in b)
        and a.get("name") == b.get("name")
    )


def _build_row(kind: str, run: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    first = run[0]
    base = {
        "turn": first["data"]["turn"],
        "step": first["data"]["step"],
        "index": _index_of(first),
        "dt": [run[i]["time"] - run[i - 1]["time"] for i in range(1, len(run))],
    }
    envelope = {"seq0": first["seq"], "time0": first["time"]}
    if kind == "tool-call-delta":
        call = _tool_call_of(first)
        row_data = {
            **base,
            "id": call["id"],
            "args": [ev["data"]["chunk"]["argumentsDelta"] for ev in run],
        }
        if "name" in call:
            row_data["name"] = call["name"]
        return {
            "type": "tool-call-chunks",
            **envelope,
            "data": row_data,
        }
    t_name = "text-chunks" if kind == "text-delta" else "reasoning-chunks"
    return {
        "type": t_name,
        **envelope,
        "data": {
            **base,
            "texts": [ev["data"]["chunk"]["text"] for ev in run],
        },
    }


def pack_chunk_runs(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Pack an event batch for storage: each run of at least MIN_RUN consecutive
    same-kind delta chunks becomes one ChunkRow.
    """
    out: List[Dict[str, Any]] = []
    kind: Optional[str] = None
    run: List[Dict[str, Any]] = []

    def flush() -> None:
        nonlocal kind, run
        if kind is not None and len(run) >= MIN_RUN:
            out.append(_build_row(kind, run))
        else:
            out.extend(run)
        kind = None
        run = []

    for event in events:
        k = _classify(event)
        if k is None:
            flush()
            out.append(event)
            continue
        last = run[-1] if run else None
        if k == kind and last is not None and _continues(last, event, k):
            run.append(event)
            continue
        flush()
        kind = k
        run = [event]
    flush()
    return out


def _malformed(tag: str, why: str) -> None:
    raise ValueError(f"malformed {tag} storage row: {why}")


def _validate_run_data(tag: str, data: Dict[str, Any], payload_key: str) -> List[str]:
    for key in ("turn", "step", "index"):
        if not _is_number(data.get(key)):
            _malformed(tag, "turn/step/index must be numbers")
    payload = data.get(payload_key)
    if not isinstance(payload, list) or len(payload) == 0 or any(not isinstance(x, str) for x in payload):
        _malformed(tag, f"{payload_key} must be a non-empty string array")
    dt = data.get("dt")
    if not isinstance(dt, list) or any(not _is_safe_integer(g) for g in dt):
        _malformed(tag, "dt must be an array of safe integers")
    if len(dt) != len(payload) - 1:
        _malformed(tag, f"dt length {len(dt)} does not match {len(payload)} members")
    return payload


def _validate_row(value: Dict[str, Any], tag: str) -> Dict[str, Any]:
    if not _has_exact_keys(value, ["type", "seq0", "time0", "data"]):
        _malformed(tag, "envelope must be exactly {type, seq0, time0, data}")
    seq0 = value.get("seq0")
    if not _is_safe_integer(seq0) or seq0 < 0:
        _malformed(tag, "seq0 must be a non-negative safe integer")
    time0 = value.get("time0")
    if not _is_safe_integer(time0):
        _malformed(tag, "time0 must be a safe integer")
    data = value.get("data")
    if not isinstance(data, dict):
        _malformed(tag, "data must be an object")

    if tag == "tool-call-chunks":
        with_name = _has_exact_keys(data, ["turn", "step", "index", "id", "name", "dt", "args"])
        if not with_name and not _has_exact_keys(data, ["turn", "step", "index", "id", "dt", "args"]):
            _malformed(tag, "data must be exactly {turn, step, index, id, name?, dt, args}")
        if not isinstance(data.get("id"), str) or (with_name and not isinstance(data.get("name"), str)):
            _malformed(tag, "id (and name when present) must be strings")
        payload = _validate_run_data(tag, data, "args")
    else:
        if not _has_exact_keys(data, ["turn", "step", "index", "dt", "texts"]):
            _malformed(tag, "data must be exactly {turn, step, index, dt, texts}")
        payload = _validate_run_data(tag, data, "texts")

    if len(payload) - 1 > MAX_SAFE_INTEGER - seq0:
        _malformed(tag, "member seqs must stay safe integers")
    cur_time = time0
    for gap in data["dt"]:
        cur_time += gap
        if abs(cur_time) > MAX_SAFE_INTEGER:
            _malformed(tag, "member times must stay safe integers")
    return value


def _expand_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    tag = row["type"]
    data = row["data"]
    members = data["args"] if tag == "tool-call-chunks" else data["texts"]
    events: List[Dict[str, Any]] = []
    cur_time = row["time0"]
    for k in range(len(members)):
        if k > 0:
            cur_time += data["dt"][k - 1]
        if tag == "text-chunks":
            chunk: Dict[str, Any] = {"type": "text-delta", "index": data["index"], "text": members[k]}
        elif tag == "reasoning-chunks":
            chunk = {"type": "reasoning-delta", "index": data["index"], "text": members[k]}
        else:
            chunk = {
                "type": "tool-call-delta",
                "index": data["index"],
                "id": data["id"],
                "argumentsDelta": members[k],
            }
            if "name" in data:
                chunk["name"] = data["name"]
        events.append({
            "type": "assistant/chunk",
            "seq": row["seq0"] + k,
            "time": cur_time,
            "data": {
                "turn": data["turn"],
                "step": data["step"],
                "chunk": chunk,
            },
        })
    return events


def decode_storage_record(value: Any) -> List[Dict[str, Any]]:
    """
    Decode one parsed JSONL line value into the session event(s) it stores.
    """
    if not isinstance(value, dict):
        return [value]
    tag = value.get("type")
    if tag not in ("text-chunks", "reasoning-chunks", "tool-call-chunks"):
        return [value]
    return _expand_row(_validate_row(value, tag))


packChunkRuns = pack_chunk_runs
decodeStorageRecord = decode_storage_record
isChunkRow = is_chunk_row
chunkRowLength = chunk_row_length
