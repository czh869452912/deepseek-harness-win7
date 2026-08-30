"""
Surface layer on top of the session event log: an ordered view of events
that produce LLM messages. The append-only log remains the source of truth.
"""

from typing import Any, Dict, List, Optional, Set, Tuple, Union


SURFACE_EVENT_TYPES: Set[str] = {
    "user/message",
    "assistant/message",
    "tool/result",
}


def is_surface_eligible_type(event_type: str) -> bool:
    """Whether an event type can join the model-visible surface."""
    return event_type in SURFACE_EVENT_TYPES


def is_surface_event(event: Dict[str, Any]) -> bool:
    """Narrow an event to a surface-eligible event carrying its required marker."""
    if event.get("type") not in SURFACE_EVENT_TYPES:
        return False
    return event.get("surfaceOp") is not None


def is_append_surface_event(event: Dict[str, Any]) -> bool:
    """Narrow an event to an append-origin surface event."""
    return is_surface_event(event) and event.get("surfaceOp") == "append"


def is_replacement_surface_event(event: Dict[str, Any]) -> bool:
    """Narrow an event to a surface replacement node."""
    return is_surface_event(event) and event.get("surfaceOp") != "append"


def derive_event_message(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Project a single event into the LLM message it derives to, or None when it produces none.
    """
    etype = event.get("type")
    edata = event.get("data")
    if not isinstance(edata, dict):
        return None

    if etype == "user/message":
        if "role" in edata:
            return edata
        res = {
            "role": "user",
            "content": edata.get("content", ""),
            "source": edata.get("source"),
        }
        if "id" in edata:
            res["id"] = edata["id"]
        return res

    elif etype == "assistant/message":
        msg = edata.get("message")
        if not isinstance(msg, dict):
            return None
        content = msg.get("content", [])
        if isinstance(content, list) and len(content) == 0:
            return None
        if isinstance(content, str) and len(content) == 0:
            return None
        return msg

    elif etype == "tool/result":
        msg = edata.get("message")
        if isinstance(msg, dict):
            return msg
        if "role" in edata:
            return edata
        return None

    return None


class SurfaceFoldReplacement:
    """One replacement operation observed while folding a session surface."""

    def __init__(self, seq: int, start: int, end: int, shadowed_seqs: List[int]):
        self.seq = seq
        self.start = start
        self.end = end
        self.shadowed_seqs = shadowed_seqs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "start": self.start,
            "end": self.end,
            "shadowed_seqs": list(self.shadowed_seqs),
        }


class SurfaceFoldResult:
    """Complete result of replaying the surface operations in a session log."""

    def __init__(self, nodes: List[int], replacements: List[SurfaceFoldReplacement], replace_generation: int = 0):
        self.nodes = list(nodes)
        self.replacements = list(replacements)
        self.replace_generation = replace_generation
        self.replaceGeneration = replace_generation


class SurfacePlan:
    """A validated surface transition before committing to fold state."""

    def __init__(
        self,
        kind: str,
        seq: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
        start_idx: Optional[int] = None,
        end_idx: Optional[int] = None,
        shadowed_seqs: Optional[List[int]] = None,
    ):
        self.kind = kind  # 'append' or 'replace'
        self.seq = seq
        self.start = start
        self.end = end
        self.start_idx = start_idx
        self.end_idx = end_idx
        self.shadowed_seqs = shadowed_seqs or []


def _is_event_seq(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


def _surface_op_of(event: Dict[str, Any]) -> Optional[Union[str, Dict[str, Any]]]:
    etype = event.get("type", "")
    op = event.get("surfaceOp")

    if not is_surface_eligible_type(etype):
        if op is not None:
            raise ValueError(f'session event "{etype}" is not surface-eligible and cannot carry surfaceOp')
        if event.get("sourceEventSeqs") is not None:
            raise ValueError(f'session event "{etype}" is not surface-eligible and cannot carry sourceEventSeqs')
        return None

    if op is None:
        raise ValueError(f'session event "{etype}" is surface-eligible and requires a surfaceOp marker')

    if op == "append":
        return "append"

    if isinstance(op, dict):
        if op.get("op") == "replace" and _is_event_seq(op.get("start")) and _is_event_seq(op.get("end")):
            return op
        raise ValueError(f'session event "{etype}" carries an invalid replace surfaceOp: {op}')

    raise ValueError(f'session event "{etype}" carries an invalid surfaceOp: {op}')


def _assert_provenance(event: Dict[str, Any], shadowed_seqs: List[int]) -> None:
    raw = event.get("sourceEventSeqs")
    sources: Set[int] = set()
    current_seq = event.get("seq", 0)

    if raw is not None:
        if not isinstance(raw, list):
            raise ValueError(f"sourceEventSeqs on event at seq {current_seq} must be an array when present")
        if len(raw) == 0 and event.get("type") != "assistant/message":
            raise ValueError("sourceEventSeqs must not be empty except on assistant/message")

        for s in raw:
            if not _is_event_seq(s):
                raise ValueError(f'session event "{event.get("type")}" sourceEventSeqs must densely contain non-negative safe integers')
            if s in sources:
                raise ValueError("sourceEventSeqs must not contain duplicates")
            sources.add(s)
            if s >= current_seq:
                raise ValueError(f"sourceEventSeqs must reference earlier events: {s} >= current seq {current_seq}")

    missing = [seq for seq in shadowed_seqs if seq not in sources]
    if missing:
        missing_str = ", ".join(str(s) for s in missing)
        raise ValueError(f"surface replace: sourceEventSeqs must include every shadowed surface node; missing {missing_str}")


def _is_deep_equal_json(a: Any, b: Any) -> bool:
    if a == b:
        return True
    if isinstance(a, list) or isinstance(b, list):
        if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
            return False
        return all(_is_deep_equal_json(x, y) for x, y in zip(a, b))
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if set(a.keys()) != set(b.keys()):
        return False
    return all(_is_deep_equal_json(a[k], b[k]) for k in a)


def _assert_tool_result_rewrite(
    event: Dict[str, Any],
    shadowed_seqs: List[int],
    log: List[Dict[str, Any]],
    base_seq: int = 0,
) -> None:
    if event.get("type") != "tool/result":
        return
    if len(shadowed_seqs) != 1:
        raise ValueError("tool/result surface replacement must rewrite exactly one current node")
    for original_seq in shadowed_seqs:
        idx = original_seq - base_seq
        original = log[idx] if 0 <= idx < len(log) else None
        if not original or original.get("type") != "tool/result":
            raise ValueError("tool/result surface replacement must target a current tool/result")
        orig_data = dict(original.get("data", {}))
        repl_data = dict(event.get("data", {}))
        orig_msg = dict(orig_data.get("message", {})) if isinstance(orig_data.get("message"), dict) else {}
        repl_msg = dict(repl_data.get("message", {})) if isinstance(repl_data.get("message"), dict) else {}
        orig_content = orig_msg.get("content", [])
        repl_content = repl_msg.get("content", [])
        if isinstance(orig_content, list) and orig_content and isinstance(orig_content[0], dict):
            orig_first = dict(orig_content[0])
            orig_first["content"] = None
            orig_msg["content"] = [orig_first]
        else:
            orig_msg["content"] = None
        if isinstance(repl_content, list) and repl_content and isinstance(repl_content[0], dict):
            repl_first = dict(repl_content[0])
            repl_first["content"] = None
            repl_msg["content"] = [repl_first]
        else:
            repl_msg["content"] = None
        orig_rest = dict(orig_data)
        orig_rest["message"] = orig_msg
        repl_rest = dict(repl_data)
        repl_rest["message"] = repl_msg
        if not _is_deep_equal_json(orig_rest, repl_rest):
            raise ValueError("tool/result surface replacement may change only content")


class _SurfaceFoldState:
    def __init__(self):
        self.nodes: List[int] = []
        self.replace_generation: int = 0


def _plan_surface_event_state(
    state: _SurfaceFoldState,
    event: Dict[str, Any],
    expected_seq: int,
    events: List[Dict[str, Any]],
    base_seq: int,
) -> Optional[SurfacePlan]:
    event_seq = event.get("seq", expected_seq)
    if event_seq != expected_seq:
        raise ValueError(f"session event seq {event_seq} is not contiguous; expected {expected_seq}")
    surface_op = _surface_op_of(event)
    if surface_op is None:
        return None
    if surface_op == "append":
        _assert_provenance(event, [])
        return SurfacePlan(kind="append", seq=event_seq)
    start_seq = surface_op["start"]
    end_seq = surface_op["end"]
    try:
        start_idx = state.nodes.index(start_seq)
    except ValueError:
        raise ValueError(f"surface replace: start seq {start_seq} not found in surface")
    try:
        end_idx = state.nodes.index(end_seq)
    except ValueError:
        raise ValueError(f"surface replace: end seq {end_seq} not found in surface")
    if start_idx > end_idx:
        raise ValueError(
            f"surface replace: start seq {start_seq} (index {start_idx}) is after end seq {end_seq} (index {end_idx})"
        )
    shadowed_seqs = state.nodes[start_idx : end_idx + 1]
    _assert_provenance(event, shadowed_seqs)
    _assert_tool_result_rewrite(event, shadowed_seqs, events, base_seq)
    return SurfacePlan(
        kind="replace",
        seq=event_seq,
        start=start_seq,
        end=end_seq,
        start_idx=start_idx,
        end_idx=end_idx,
        shadowed_seqs=shadowed_seqs,
    )


def _apply_surface_plan_state(
    state: _SurfaceFoldState,
    plan: Optional[SurfacePlan],
) -> Optional[SurfaceFoldReplacement]:
    if plan is None:
        return None
    if plan.kind == "append":
        state.nodes.append(plan.seq)
        return None
    elif plan.kind == "replace":
        assert plan.start_idx is not None and plan.end_idx is not None
        state.nodes[plan.start_idx : plan.end_idx + 1] = [plan.seq]
        state.replace_generation += 1
        return SurfaceFoldReplacement(
            seq=plan.seq,
            start=plan.start or 0,
            end=plan.end or 0,
            shadowed_seqs=plan.shadowed_seqs,
        )
    return None


def _apply_surface_event_state(
    state: _SurfaceFoldState,
    event: Dict[str, Any],
    expected_seq: int,
    events: List[Dict[str, Any]],
    base_seq: int,
) -> Optional[SurfaceFoldReplacement]:
    plan = _plan_surface_event_state(state, event, expected_seq, events, base_seq)
    return _apply_surface_plan_state(state, plan)


class SurfaceManager:
    """
    Incremental ordered surface view and append-boundary validator.
    Maintains model-visible sequence order and tracks monotonic replace_generation.
    """

    def __init__(self, log: List[Dict[str, Any]], base_seq: int = 0):
        self.log = log
        self.base_seq = base_seq
        self._state = _SurfaceFoldState()
        self._last_processed_seq = base_seq - 1
        self._pending_plan: Optional[Tuple[Dict[str, Any], int, Optional[SurfacePlan]]] = None

    @property
    def replace_generation(self) -> int:
        if self._last_processed_seq < self.base_seq + len(self.log) - 1:
            self._process_delta()
        return self._state.replace_generation

    @property
    def replaceGeneration(self) -> int:
        return self.replace_generation

    @property
    def nodes(self) -> List[int]:
        if self._last_processed_seq < self.base_seq + len(self.log) - 1:
            self._process_delta()
        return list(self._state.nodes)

    def validate_next(self, event: Dict[str, Any]) -> None:
        """
        Validate candidate event without mutating the committed surface.
        """
        if self._last_processed_seq < self.base_seq + len(self.log) - 1:
            self._process_delta()
        expected_seq = self.base_seq + len(self.log)
        plan = _plan_surface_event_state(self._state, event, expected_seq, self.log, self.base_seq)
        self._pending_plan = (event, expected_seq, plan)

    def _process_delta(self) -> None:
        tail_seq = self.base_seq + len(self.log) - 1
        seq = self._last_processed_seq + 1
        while seq <= tail_seq:
            index = seq - self.base_seq
            event = self.log[index]
            pending = self._pending_plan
            if pending is not None and pending[0] is event and pending[1] == seq:
                _apply_surface_plan_state(self._state, pending[2])
            else:
                _apply_surface_event_state(self._state, event, seq, self.log, self.base_seq)
            if pending is not None and pending[1] <= seq:
                self._pending_plan = None
            self._last_processed_seq = seq
            seq += 1


def fold_surface(events: List[Dict[str, Any]]) -> SurfaceFoldResult:
    """
    Replay a complete session log through the canonical surface fold.
    """
    state = _SurfaceFoldState()
    replacements: List[SurfaceFoldReplacement] = []

    for index, event in enumerate(events):
        rep = _apply_surface_event_state(state, event, index, events, 0)
        if rep is not None:
            replacements.append(rep)

    return SurfaceFoldResult(nodes=state.nodes, replacements=replacements, replace_generation=state.replace_generation)


# --- Tool Pairing Balance Helpers ---


def _event_delta(event: Dict[str, Any]) -> int:
    etype = event.get("type")
    if etype == "assistant/message":
        edata = event.get("data", {})
        msg = edata.get("message", edata)
        tool_calls = msg.get("tool_calls", [])
        return len(tool_calls)
    elif etype == "tool/result":
        return -1
    return 0


def tool_pairing_balanced_before(session_events: List[Dict[str, Any]], surface_nodes: List[int], seq: int) -> bool:
    """
    Whether the cut immediately before a current surface sequence is tool-pairing balanced.
    """
    if seq not in surface_nodes:
        raise ValueError(f"tool-pairing balance: surface seq {seq} not found")

    idx = surface_nodes.index(seq)
    in_progress = 0
    for s in surface_nodes[:idx]:
        if s >= len(session_events):
            raise ValueError(f"tool-pairing balance: seq {s} out of event log bounds")
        in_progress += _event_delta(session_events[s])
        if in_progress < 0:
            raise ValueError(f"tool-pairing balance: tool/result at seq {s} has no matching tool-call")

    return in_progress == 0


def tool_pairing_balanced_after(session_events: List[Dict[str, Any]], surface_nodes: List[int], seq: int) -> bool:
    """
    Whether the cut immediately after a current surface sequence is tool-pairing balanced.
    """
    if seq not in surface_nodes:
        raise ValueError(f"tool-pairing balance: surface seq {seq} not found")

    idx = surface_nodes.index(seq)
    in_progress = 0
    for s in surface_nodes[: idx + 1]:
        if s >= len(session_events):
            raise ValueError(f"tool-pairing balance: seq {s} out of event log bounds")
        in_progress += _event_delta(session_events[s])
        if in_progress < 0:
            raise ValueError(f"tool-pairing balance: tool/result at seq {s} has no matching tool-call")

    return in_progress == 0
