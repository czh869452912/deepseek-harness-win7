"""Package-owned compaction invariants from the pinned upstream companion."""

import math
import weakref
from typing import Any, Callable, Dict, Optional, Set

from dsh.cordis.plugin import Plugin
from dsh.core.session import is_replacement_surface_event
from dsh.core.session.json import UNDEFINED
from dsh.diagnostics.invariants import registration_result

PACKAGE_NAME = "@deepseek-ai/dsh-compaction"
TRANSACTIONS = {"session/end-seed", "compaction/start", "compaction/summary", "compaction/end"}


def _string(value: Any) -> str:
    if value is UNDEFINED:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _same(left: Any, right: Any) -> bool:
    # JavaScript strict equality keeps booleans distinct from JSON numbers.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return left == right


class _Trace:
    def __init__(self) -> None:
        self.open_turn: Any = None
        self.compaction: Optional[Dict[str, Any]] = None


def _id(value: Any, label: str, fail: Callable[[str], None]) -> None:
    if not isinstance(value, str) or not value:
        fail(label + " must be a non-empty string")


def _source(kind: str, value: Any, expected: Any, fail: Callable[[str], None]) -> None:
    if value is not UNDEFINED:
        _id(value, kind + " sourceCommandId", fail)
    if not _same(value, expected):
        fail("{} sourceCommandId {} does not match compaction/start sourceCommandId {}".format(
            kind, _string(value), _string(expected)))


def _owner(owner: Any, open_turn: Any, kind: str, fail: Callable[[str], None]) -> None:
    if owner is None:
        if open_turn is not None:
            fail("{} is standalone but turn {} is open".format(kind, _string(open_turn)))
        return
    if open_turn is None:
        fail("{} for turn {} appended outside any open turn".format(kind, _string(owner)))
    if not _same(owner, open_turn):
        fail("{} names turn {} but open turn is {}".format(kind, _string(owner), _string(open_turn)))


def _boundary(trace: _Trace, event: Dict[str, Any], fail: Callable[[str], None]) -> None:
    if event["type"] not in ("turn/start", "turn/end") or trace.compaction is None:
        return
    turn = trace.compaction["turn"]
    owner = "standalone compaction" if turn is None else "compaction for turn " + _string(turn)
    fail(event["type"] + " cannot cross an open " + owner)


def _apply_boundary(trace: _Trace, event: Dict[str, Any]) -> bool:
    if event["type"] == "turn/start":
        trace.open_turn = event["data"]["turn"]
        return True
    if event["type"] == "turn/end":
        trace.open_turn = None
        return True
    return False


def _validate(trace: _Trace, event: Dict[str, Any], fail: Callable[[str], None]) -> Optional[Dict[str, Any]]:
    kind = event["type"]
    if kind == "session/end-seed":
        return {"kind": "end-seed"}
    data = event["data"]
    opened = trace.compaction
    if kind == "user/message" and is_replacement_surface_event(event):
        source = data["source"]
        if source.get("kind") == "plugin" and source.get("plugin") == "compact":
            identity = source.get("compactionId", UNDEFINED)
            command = source.get("sourceCommandId", UNDEFINED)
            _id(identity, "compaction checkpoint compactionId", fail)
            if command is not UNDEFINED:
                _id(command, "compaction checkpoint sourceCommandId", fail)
            if opened is None:
                fail("compaction checkpoint has no matching compaction/start")
            if identity != opened["compactionId"]:
                fail("compaction checkpoint id {} does not match compaction/start id {}".format(
                    identity, opened["compactionId"]))
            _source("compaction checkpoint", command, opened["sourceCommandId"], fail)
        return None
    if kind not in TRANSACTIONS:
        return None
    identity = data.get("compactionId", UNDEFINED)
    command = data.get("sourceCommandId", UNDEFINED)
    _id(identity, kind + " compactionId", fail)
    if command is not UNDEFINED:
        _id(command, kind + " sourceCommandId", fail)
    if kind == "compaction/start":
        if opened is not None:
            owner = "standalone compaction" if opened["turn"] is None else "turn " + _string(opened["turn"])
            fail("compaction/start while " + owner + " is still compacting")
        turn = data.get("turn", UNDEFINED)
        _owner(turn, trace.open_turn, kind, fail)
        return dict(kind="start", compactionId=identity, sourceCommandId=command, startSeq=event["seq"], turn=turn)
    if opened is None:
        fail(kind + " has no matching compaction/start")
    if identity != opened["compactionId"]:
        fail("{} id {} does not match compaction/start id {}".format(kind, identity, opened["compactionId"]))
    _source(kind, command, opened["sourceCommandId"], fail)
    if kind == "compaction/summary":
        _owner(opened["turn"], trace.open_turn, kind, fail)
        if opened["summarized"]:
            fail("compaction/summary repeated within one compaction")
        seqs, span = data["shadowedSeqs"], data["shadowedRange"]
        if not seqs:
            fail("compaction/summary shadowedSeqs must be non-empty")
        if not _same(seqs[0], span["start"]) or not _same(seqs[-1], span["end"]):
            fail("compaction/summary shadowedRange must match the first and last shadowedSeqs")
        count = data.get("shadowedTokenCount", UNDEFINED)
        if (isinstance(count, bool) or not isinstance(count, (int, float))
                or not 0 <= count <= 9007199254740991 or not math.isfinite(count) or count != int(count)):
            fail("compaction/summary shadowedTokenCount must be a non-negative safe integer")
        return dict(opened, kind="summary")
    if not _same(data.get("turn", UNDEFINED), opened["turn"]):
        fail("compaction/end owner {} does not match compaction/start owner {}".format(
            _string(data.get("turn", UNDEFINED)), _string(opened["turn"])))
    _owner(opened["turn"], trace.open_turn, kind, fail)
    if "error" not in data and not opened["summarized"]:
        fail("successful compaction/end requires one compaction/summary")
    return {"kind": "end"}


def _apply(transition: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if transition["kind"] in ("start", "summary"):
        return {key: transition[key] for key in ("compactionId", "sourceCommandId", "startSeq", "turn")}
    return None


def _orphans(events: Any) -> Set[int]:
    stale: Set[int] = set()
    start: Optional[int] = None
    for event in events:
        if event["type"] == "compaction/start":
            start = event["seq"]
        elif event["type"] == "compaction/end":
            start = None
        elif event["type"] == "session/end-seed" and start is not None:
            stale.add(start)
            start = None
    return stale


def install(ctx: Any, fail: Callable[[str], None]) -> Callable[[], None]:
    traces: Any = weakref.WeakKeyDictionary()
    staged: Dict[int, Any] = {}

    def advance(trace: _Trace, transition: Dict[str, Any]) -> None:
        trace.compaction = _apply(transition)
        if trace.compaction is not None:
            trace.compaction["summarized"] = transition["kind"] == "summary"

    def seed(session: Any) -> _Trace:
        trace = _Trace()
        traces[session] = trace
        stale = _orphans(session.events)
        for event in session.events:
            if trace.compaction is None or trace.compaction["startSeq"] not in stale:
                _boundary(trace, event, fail)
            transition = _validate(trace, event, fail)
            if transition is not None:
                advance(trace, transition)
            _apply_boundary(trace, event)
        return trace

    def trace_for(session: Any) -> _Trace:
        trace = traces.get(session)
        return seed(session) if trace is None else trace

    for session in ctx.get("sessions").list():
        seed(session)
    ctx.on("session/created", seed, global_listener=True)

    def published(session: Any, event: Dict[str, Any]) -> None:
        trace = trace_for(session)
        _boundary(trace, event, fail)
        if _apply_boundary(trace, event) or event["type"] not in TRANSACTIONS:
            return
        candidate = staged.pop(id(event), None)
        if candidate is None or candidate[0]() is not event or candidate[1]() is not session:
            fail("compaction event published without pre-commit validation")
        advance(trace, candidate[2])

    def dispatch(_mode: str, event_name: str, args: Any, *extra: Any) -> None:
        if event_name != "session/event":
            return
        session, event = args[:2]
        trace = trace_for(session)
        _boundary(trace, event, fail)
        transition = _validate(trace, event, fail)
        if transition is not None:
            identity = id(event)
            try:
                event_ref = weakref.ref(event, lambda _ref: staged.pop(identity, None))
            except TypeError:
                # Explicit emit callers may supply a plain dict. Native append
                # candidates are weak-referenceable immutable JSON objects.
                event_ref = lambda: event
            staged[identity] = (event_ref, weakref.ref(session), transition)

    ctx.on("session/event", published, global_listener=True)
    ctx.on("internal/dispatch", dispatch, global_listener=True)

    def cleanup() -> None:
        staged.clear()
        traces.clear()

    return cleanup


install.inject = ["sessions"]


class CompactionInvariantPlugin(Plugin):
    id = name = "compaction-invariant"
    inject = ["invariants"]

    def apply(self, ctx: Any) -> Any:
        return registration_result(ctx.get("invariants").register(PACKAGE_NAME, install))


def _no_state(_ctx: Any, _fail: Any) -> None:
    pass


class _OwnershipCompanion(Plugin):
    inject = ["invariants"]
    package_name = ""

    def apply(self, ctx: Any) -> Any:
        return registration_result(ctx.get("invariants").register(self.package_name, _no_state))


class CompactionBasicInvariantPlugin(_OwnershipCompanion):
    id = name = "compaction-basic-invariant"
    package_name = "@deepseek-ai/dsh-compaction-basic"


class CommandCompactInvariantPlugin(_OwnershipCompanion):
    id = name = "command-compact-invariant"
    package_name = "@deepseek-ai/dsh-command-compact"


class ToolResultPrunerInvariantPlugin(_OwnershipCompanion):
    id = name = "compaction-tool-result-pruner-invariant"
    package_name = "@deepseek-ai/dsh-compaction-tool-result-pruner"
