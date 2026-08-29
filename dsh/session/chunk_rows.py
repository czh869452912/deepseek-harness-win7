"""
Lossless row packing for `assistant/chunk` delta runs.
1:1 aligned with official `@deepseek-ai/dsh-session/chunk-rows`.
"""

from typing import Any, Dict, List, Optional, Union

MIN_RUN = 3
MAX_SAFE_INTEGER = 9007199254740991
MIN_SAFE_INTEGER = -9007199254740991


def _is_safe_integer(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool) and MIN_SAFE_INTEGER <= val <= MAX_SAFE_INTEGER


def _has_exact_keys(d: Dict[str, Any], keys: List[str]) -> bool:
    return set(d.keys()) == set(keys)


def is_chunk_row(record: Dict[str, Any]) -> bool:
    """Test whether an encoded record is a packed chunk row rather than a Session event."""
    if not isinstance(record, dict):
        return False
    rtype = record.get("type")
    return rtype in ("text-chunks", "reasoning-chunks", "tool-call-chunks")


def chunk_row_length(row: Dict[str, Any]) -> int:
    """Number of logical Session events represented by one packed row."""
    data = row.get("data", {})
    if row.get("type") == "tool-call-chunks":
        return len(data.get("args", []))
    return len(data.get("texts", []))


def _classify(event: Dict[str, Any]) -> Optional[str]:
    if not isinstance(event, dict):
        return None
    if event.get("type") != "assistant/chunk":
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
    if not isinstance(data.get("turn"), int) or not isinstance(data.get("step"), int):
        return None

    chunk = data.get("chunk")
    if not isinstance(chunk, dict) or not isinstance(chunk.get("index"), int):
        return None

    ctype = chunk.get("type")
    if ctype in ("text-delta", "reasoning-delta"):
        if _has_exact_keys(chunk, ["type", "index", "text"]) and isinstance(chunk.get("text"), str):
            return ctype
        return None
    elif ctype == "tool-call-delta":
        shape_ok = _has_exact_keys(chunk, ["type", "index", "id", "argumentsDelta"]) or (
            _has_exact_keys(chunk, ["type", "index", "id", "name", "argumentsDelta"])
            and isinstance(chunk.get("name"), str)
        )
        if shape_ok and isinstance(chunk.get("id"), str) and isinstance(chunk.get("argumentsDelta"), str):
            return ctype
        return None

    return None


def _tool_call_of(event: Dict[str, Any]) -> Dict[str, Any]:
    return event["data"]["chunk"]


def _index_of(event: Dict[str, Any]) -> int:
    return event["data"]["chunk"]["index"]


def _continues(prev: Dict[str, Any], nxt: Dict[str, Any], kind: str) -> bool:
    if nxt.get("seq") != prev.get("seq", 0) + 1:
        return False
    gap = nxt.get("time", 0) - prev.get("time", 0)
    if not _is_safe_integer(gap):
        return False
    if nxt["data"].get("turn") != prev["data"].get("turn") or nxt["data"].get("step") != prev["data"].get("step"):
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


def _build_row(kind: str, run: List[Dict[str, Any]]) -> Dict[str, Any]:
    first = run[0]
    dt: List[int] = [run[i].get("time", 0) - run[i - 1].get("time", 0) for i in range(1, len(run))]
    base: Dict[str, Any] = {
        "turn": first["data"]["turn"],
        "step": first["data"]["step"],
        "index": _index_of(first),
        "dt": dt,
    }
    envelope: Dict[str, Any] = {
        "seq0": first["seq"],
        "time0": first["time"],
    }
    if kind == "tool-call-delta":
        call = _tool_call_of(first)
        data = {
            **base,
            "id": call["id"],
            **({"name": call["name"]} if "name" in call else {}),
            "args": [ev["data"]["chunk"]["argumentsDelta"] for ev in run],
        }
        return {
            "type": "tool-call-chunks",
            **envelope,
            "data": data,
        }
    texts = [ev["data"]["chunk"]["text"] for ev in run]
    row_type = "text-chunks" if kind == "text-delta" else "reasoning-chunks"
    return {
        "type": row_type,
        **envelope,
        "data": {**base, "texts": texts},
    }


def pack_chunk_runs(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Pack an event batch for storage: each run of at least MIN_RUN consecutive
    same-kind, same-block delta chunk events becomes one ChunkRow;
    every other event passes through verbatim, in order.
    """
    out: List[Dict[str, Any]] = []
    kind: Optional[str] = None
    run: List[Dict[str, Any]] = []

    def flush():
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
    if (
        not isinstance(data.get("turn"), int)
        or not isinstance(data.get("step"), int)
        or not isinstance(data.get("index"), int)
    ):
        _malformed(tag, "turn/step/index must be numbers")
    payload = data.get(payload_key)
    if (
        not isinstance(payload, list)
        or len(payload) == 0
        or any(not isinstance(entry, str) for entry in payload)
    ):
        _malformed(tag, f"{payload_key} must be a non-empty string array")
    dt = data.get("dt")
    if not isinstance(dt, list) or any(not _is_safe_integer(gap) for gap in dt):
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
    current_time = time0
    for gap in data.get("dt", []):
        current_time += gap
        if not _is_safe_integer(current_time):
            _malformed(tag, "member times must stay safe integers")

    return value


def _expand_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    row_type = row.get("type")
    data = row.get("data", {})
    members = data.get("args") if row_type == "tool-call-chunks" else data.get("texts", [])
    events: List[Dict[str, Any]] = []
    current_time = row["time0"]
    dt_list = data.get("dt", [])

    for k in range(len(members)):
        if k > 0:
            current_time += dt_list[k - 1]
        chunk: Dict[str, Any]
        if row_type == "text-chunks":
            chunk = {"type": "text-delta", "index": data["index"], "text": members[k]}
        elif row_type == "reasoning-chunks":
            chunk = {"type": "reasoning-delta", "index": data["index"], "text": members[k]}
        elif row_type == "tool-call-chunks":
            chunk = {
                "type": "tool-call-delta",
                "index": data["index"],
                "id": data["id"],
                **({"name": data["name"]} if "name" in data else {}),
                "argumentsDelta": members[k],
            }
        else:
            raise ValueError(f"chunk-rows received unsupported row type {row_type}")

        events.append({
            "type": "assistant/chunk",
            "seq": row["seq0"] + k,
            "time": current_time,
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
    Chunk-row-tagged values validate and expand; every other value passes through as a single event.
    """
    if not isinstance(value, dict):
        return [value]
    tag = value.get("type")
    if tag not in ("text-chunks", "reasoning-chunks", "tool-call-chunks"):
        return [value]
    return _expand_row(_validate_row(value, tag))
