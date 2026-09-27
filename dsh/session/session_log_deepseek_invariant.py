"""
Package-owned invariants for DeepSeek session-log acceptance watermarks.

1:1 with reference/packages/session/session-log-deepseek/src/invariant.ts: an
acceptance watermark must name its containing session (unless it is an inherited
fork-seed record) and must identify an earlier event in the same log.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Callable, Optional

PACKAGE_NAME = "@deepseek-ai/dsh-session-log-deepseek"
name = "session-log-deepseek-invariant"
inject = ["invariants"]

ACCEPTED_EVENT_TYPE = "session-log-deepseek/delivery-accepted"


def _is_safe_integer(value: Any) -> bool:
    """`Number.isSafeInteger(value)`: a JSON boolean is not an integer here."""
    return isinstance(value, int) and not isinstance(value, bool)


def _header_value(header: Any, name_camel: str, name_snake: str) -> Any:
    """One header field under the port's attribute spelling or the reference's."""
    for attr in (name_camel, name_snake):
        if hasattr(header, attr):
            return getattr(header, attr)
    return None


def _is_inherited_seed_event(session: Any, event: Any) -> bool:
    """
    Whether this event is an inherited parent record replayed from a fork seed.

    A fork child adopts its parent's log prefix verbatim, so a watermark naming
    the parent inside that prefix is the parent's own accepted delivery, not a
    mis-attribution by this session.
    """
    header = getattr(session, "header", None)
    if header is None:
        return False
    parent_session = _header_value(header, "parentSession", "parent_session")
    seed_length = _header_value(header, "seedLength", "seed_length")
    if parent_session is None or seed_length is None:
        return False
    seq = event.get("seq")
    return _is_safe_integer(seq) and seq < seed_length


def _validate_delivery_accepted(session: Any, event: Any, fail: Callable[[str], None]) -> None:
    """Validate one acceptance watermark against its containing event and session."""
    data = event.get("data") or {}
    session_id = data.get("sessionId")
    through_seq = data.get("throughSeq")
    seq = event.get("seq")
    if session_id != getattr(session, "id", None) and not _is_inherited_seed_event(session, event):
        fail(
            "a non-inherited session-log-deepseek/delivery-accepted event must name its containing session"
        )
    if not _is_safe_integer(through_seq) or through_seq < 0 or through_seq >= seq:
        fail(
            "session-log-deepseek/delivery-accepted throughSeq must identify an earlier event, "
            "got {} at seq {}".format(through_seq, seq)
        )


def install(ctx: Any, fail: Callable[[str], None]) -> None:
    """
    Install validation for restored, newly created, and newly appended
    watermarks.
    """
    sessions = ctx.sessions if hasattr(ctx, "sessions") else ctx.get("sessions")

    def validate_session(session: Any) -> None:
        for event in list(getattr(session, "events", [])):
            if isinstance(event, dict) and event.get("type") == ACCEPTED_EVENT_TYPE:
                _validate_delivery_accepted(session, event, fail)

    if sessions is not None and hasattr(sessions, "list"):
        for session in sessions.list():
            validate_session(session)

    if hasattr(ctx, "on"):

        def on_created(session: Any, *_args: Any) -> None:
            validate_session(session)

        def on_dispatch(mode: Any, event_name: Any, args: Any, *_extra: Any) -> None:
            if event_name != "session/event":
                return
            event = args[1] if len(args) > 1 else None
            if isinstance(event, dict) and event.get("type") == ACCEPTED_EVENT_TYPE:
                _validate_delivery_accepted(args[0], event, fail)

        ctx.on("session/created", on_created, global_listener=True)
        ctx.on("internal/dispatch", on_dispatch, global_listener=True)


#: The reference's `Object.assign(install, { inject: ['sessions'] })`.
install.inject = ["sessions"]


def apply(ctx: Any) -> Optional[Any]:
    """Register this package's invariant companion."""
    invariants_svc = ctx.get("invariants") if hasattr(ctx, "get") else None
    if invariants_svc is not None and hasattr(invariants_svc, "register"):
        return registration_result(invariants_svc.register(PACKAGE_NAME, install))
    return None


from dsh.diagnostics.invariants import registration_result
