"""
Package-owned relational invariants for the session event log.
Ported 1:1 from reference packages/core/session/src/invariant.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dsh.cordis.plugin import Plugin
from dsh.core.session.repair import TOOL_NOT_STARTED

PACKAGE_NAME = "@deepseek-ai/dsh-session"


class SessionTrace:
    def __init__(self) -> None:
        self.last_seq: int = -1
        self.open_turn: Optional[int] = None
        self.open_step: Optional[int] = None
        self.next_turn: int = 1
        self.next_step: int = 1
        self.pending_calls: Set[str] = set()


class SessionTraceTransition:
    def __init__(
        self,
        last_seq: int,
        open_turn: Optional[int],
        open_step: Optional[int],
        next_turn: int,
        next_step: int,
        pending_calls_op: Tuple[Any, ...],
    ) -> None:
        self.last_seq = last_seq
        self.open_turn = open_turn
        self.open_step = open_step
        self.next_turn = next_turn
        self.next_step = next_step
        self.pending_calls_op = pending_calls_op


#: `String(value)` for the nullable trace fields a failure message renders
#: (`null` in JavaScript, never Python's `None`).
def _js(value: Any) -> Any:
    return "null" if value is None else value


def _require_open_step(
    trace: SessionTrace,
    kind: str,
    turn: int,
    step: int,
    fail: Callable[[str], None],
) -> None:
    if trace.open_turn != turn or trace.open_step != step:
        fail(f"{kind} names turn {turn}/step {step} but open is turn {_js(trace.open_turn)}/step {_js(trace.open_step)}")


def validate_event(
    trace: SessionTrace,
    event: Dict[str, Any],
    fail: Callable[[str], None],
) -> SessionTraceTransition:
    seq = event.get("seq", 0)
    if seq <= trace.last_seq:
        fail(f"seq must strictly increase: saw {seq} after {trace.last_seq}")

    open_turn = trace.open_turn
    open_step = trace.open_step
    next_turn = trace.next_turn
    next_step = trace.next_step
    pending_calls_op: Tuple[Any, ...] = ("none",)

    etype = event.get("type")
    data = event.get("data", {})

    if etype == "turn/start":
        ev_turn = data.get("turn")
        if trace.open_turn is not None:
            fail(f"turn/start {ev_turn} while turn {trace.open_turn} is still open")
        if ev_turn != trace.next_turn:
            fail(f"turn/start expected turn {trace.next_turn}, got {ev_turn}")
        open_turn = ev_turn
        next_step = 1

    elif etype == "turn/end":
        ev_turn = data.get("turn")
        if trace.open_turn != ev_turn:
            fail(f"turn/end {ev_turn} does not match open turn {_js(trace.open_turn)}")
        if trace.open_step is not None:
            fail(f"turn/end {ev_turn} while step {trace.open_step} is still open")
        open_turn = None
        next_turn += 1

    elif etype == "step/start":
        ev_turn = data.get("turn")
        ev_step = data.get("step")
        if trace.open_turn != ev_turn:
            fail(f"step/start in turn {ev_turn} but open turn is {_js(trace.open_turn)}")
        if trace.open_step is not None:
            fail(f"step/start {ev_step} while step {trace.open_step} is still open")
        if ev_step != trace.next_step:
            fail(f"step/start expected step {trace.next_step} in turn {ev_turn}, got {ev_step}")
        open_step = ev_step

    elif etype == "step/end":
        _require_open_step(trace, "step/end", data.get("turn"), data.get("step"), fail)
        pending_calls_op = ("clear",)
        open_step = None
        next_step += 1

    elif etype == "assistant/chunk":
        _require_open_step(trace, "assistant/chunk", data.get("turn"), data.get("step"), fail)

    elif etype == "assistant/message":
        _require_open_step(trace, "assistant/message", data.get("turn"), data.get("step"), fail)

    elif etype == "tool/call":
        _require_open_step(trace, "tool/call", data.get("turn"), data.get("step"), fail)
        cid = data.get("callId")
        if cid:
            pending_calls_op = ("add", cid)

    elif etype == "tool/result":
        surface_op = event.get("surfaceOp")
        if surface_op != "append":
            if trace.open_turn is None:
                fail("tool/result surface replacement appended outside any open turn")
        else:
            _require_open_step(trace, "tool/result", data.get("turn"), data.get("step"), fail)
            msg = data.get("message", {})
            call_id = None
            if isinstance(msg, dict):
                src = msg.get("source", {})
                if isinstance(src, dict):
                    call_id = src.get("callId")

            content = msg.get("content", [])
            is_error = isinstance(content, list) and len(content) > 0 and isinstance(content[0], dict) and content[0].get("isError") is True
            err_code = data.get("error", {}).get("code") if isinstance(data.get("error"), dict) else None
            synthetic_not_started = is_error and err_code == TOOL_NOT_STARTED

            if call_id and call_id not in trace.pending_calls and not synthetic_not_started:
                fail(f"tool/result for {call_id} with no prior tool/call in this step")
            if call_id:
                pending_calls_op = ("delete", call_id)

    elif etype in ("request/header", "request/context"):
        if trace.open_turn is None:
            fail(f"{etype} appended outside any open turn (core execution events must be turn-enclosed)")

    return SessionTraceTransition(
        last_seq=seq,
        open_turn=open_turn,
        open_step=open_step,
        next_turn=next_turn,
        next_step=next_step,
        pending_calls_op=pending_calls_op,
    )


def apply_transition(trace: SessionTrace, transition: SessionTraceTransition) -> None:
    trace.last_seq = transition.last_seq
    trace.open_turn = transition.open_turn
    trace.open_step = transition.open_step
    trace.next_turn = transition.next_turn
    trace.next_step = transition.next_step

    op = transition.pending_calls_op[0]
    if op == "add":
        trace.pending_calls.add(transition.pending_calls_op[1])
    elif op == "delete":
        trace.pending_calls.discard(transition.pending_calls_op[1])
    elif op == "clear":
        trace.pending_calls.clear()


class SessionInvariantPlugin(Plugin):
    """
    Companion invariant plugin checking session relational rules.
    Mounted beside InvariantRegistry.
    """

    id = "session-invariant"
    name = "session-invariant"
    inject = ["invariants"]

    def apply(self, ctx: Any) -> Any:
        invariants_svc = ctx.get("invariants")
        if not invariants_svc:
            return

        def installer(target_ctx: Any, fail: Callable[[str], None]) -> None:
            # Keyed by the Session OBJECT (its default identity hash), mirroring
            # the reference `WeakMap<Session, SessionTrace>`: two distinct
            # Session objects that happen to share a session id must not share
            # trace state.
            traces: Dict[Any, SessionTrace] = {}
            # Staged transitions are keyed by the event's identity. The event is
            # stored alongside so its id cannot be reused while the transition
            # is pending (the reference keys the WeakMap on the event object
            # itself, which pins that identity for as long as the entry lives).
            staged: Dict[int, Tuple[Any, Dict[str, Any], SessionTrace, SessionTraceTransition]] = {}

            def fresh_trace() -> SessionTrace:
                return SessionTrace()

            def seed_session(session: Any) -> SessionTrace:
                trace = fresh_trace()
                traces[session] = trace
                for ev in session.events:
                    transition = validate_event(trace, ev, fail)
                    apply_transition(trace, transition)
                return trace

            def trace_for(session: Any) -> SessionTrace:
                if session not in traces:
                    return seed_session(session)
                return traces[session]

            sessions_svc = target_ctx.get("sessions")
            if sessions_svc:
                for sess in sessions_svc.list():
                    seed_session(sess)

            def on_created(session: Any) -> None:
                seed_session(session)

            target_ctx.on("session/created", on_created, global_listener=True)

            def on_event(session: Any, event: Dict[str, Any]) -> None:
                staged_item = staged.pop(id(event), None)
                if staged_item is None or staged_item[0] is not session or staged_item[1] is not event:
                    fail("session/event reached publication without matching pre-commit validation")
                    return
                apply_transition(staged_item[2], staged_item[3])

            target_ctx.on("session/event", on_event, global_listener=True)

            def on_dispatch(mode: str, event_name: str, args: List[Any], *extra: Any) -> None:
                if event_name != "session/event":
                    return
                session, event = args[0], args[1]
                trace = trace_for(session)
                transition = validate_event(trace, event, fail)
                staged[id(event)] = (session, event, trace, transition)

            target_ctx.on("internal/dispatch", on_dispatch, global_listener=True)

        if hasattr(invariants_svc, "register"):
            # The registration disposer is the companion fiber's cleanup: the
            # reference companion RETURNS it, so disposing the companion removes
            # every listener the registration installed.
            return invariants_svc.register(PACKAGE_NAME, installer)
        return None


# Module-level apply for convenience
def apply(ctx: Any) -> Any:
    plugin = SessionInvariantPlugin()
    return plugin.apply(ctx)
