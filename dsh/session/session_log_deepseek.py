"""
Incremental session-log contribution for official DeepSeek LLM API requests.

1:1 with reference/packages/session/session-log-deepseek/src/index.ts: accepted
sequence watermarks live in the canonical log, so restart recovery can
conservatively resend uncertain tails without maintaining another store.

LEGAL_ADAPTATION (Python 3.8.10): the reference keys its acceptance fold with a
`WeakMap<Session, AcceptanceFold>`; the equivalent here is a
`weakref.WeakKeyDictionary` keyed by the Session object, so the same session
identity folds incrementally and a collected Session drops its cache.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import weakref
from typing import Any, Callable, Dict, Optional

from dsh.cordis.plugin import Plugin

__all__ = [
    "ACCEPTED_EVENT_TYPE",
    "SessionLogDeepSeekPlugin",
    "accepted_through",
    "acceptedThrough",
    "apply",
    "name",
]

#: Plugin row name this package mounts as.
name = "session-log-deepseek"

#: Services required to resolve sessions and contribute the request field.
inject = ["deepseekLlmApiExtensions", "sessions"]

#: The canonical event that records one accepted delivery.
ACCEPTED_EVENT_TYPE = "session-log-deepseek/delivery-accepted"

#: Session identity -> the acceptance fold already computed for that session.
_acceptance_folds: "weakref.WeakKeyDictionary[Any, Dict[str, int]]" = weakref.WeakKeyDictionary()


def _is_safe_integer(value: Any) -> bool:
    """`Number.isSafeInteger(value)`: a JSON boolean is not an integer here."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonempty_string(value: Any) -> bool:
    """`typeof value === 'string' && value.length > 0`."""
    return isinstance(value, str) and len(value) > 0


def accepted_through(session: Any) -> int:
    """
    Highest confirmed sequence for this exact session identity.

    A malformed acceptance watermark fails closed: it is a durable record that
    the fold cannot honor, so the request must not be prepared from it.

    @param session: canonical log whose matching acceptance events are folded.
    @returns: the greatest accepted sequence, or `-1` before any accepted
        request.
    """
    previous = _acceptance_folds.get(session)
    through_seq = previous["throughSeq"] if previous is not None else -1
    events = session.events
    start = previous["scannedEvents"] if previous is not None else 0
    for index in range(start, len(events)):
        event = events[index]
        if event.get("type") != ACCEPTED_EVENT_TYPE:
            continue
        data = event.get("data") or {}
        watermark = data.get("throughSeq")
        seq = event.get("seq")
        if (
            not _is_nonempty_string(data.get("sessionId"))
            or not _is_safe_integer(watermark)
            or watermark < 0
            or watermark >= seq
        ):
            raise ValueError(
                "session-log-deepseek: malformed acceptance watermark at seq {}".format(seq)
            )
        if data.get("sessionId") != session.id:
            continue
        through_seq = max(through_seq, watermark)
    _acceptance_folds[session] = {"scannedEvents": len(events), "throughSeq": through_seq}
    return through_seq


acceptedThrough = accepted_through


def _session_id_of(request: Any) -> Optional[str]:
    """The request's session identity, under either a mapping or object shape."""
    if isinstance(request, dict):
        return request.get("sessionId")
    return getattr(request, "sessionId", None)


def _header_json(session: Any) -> Dict[str, Any]:
    """
    The session header as the wire carries it.

    The reference contributes `session.header`, which IS the JSON header object;
    this port models it as a `SessionHeader`, so `to_dict()` produces the same
    JSON value (LEGAL_ADAPTATION: value-identical, not identity-identical).
    """
    header = session.header
    to_dict = getattr(header, "to_dict", None)
    return to_dict() if callable(to_dict) else dict(header)


def apply(ctx: Any, config: Optional[Dict[str, Any]] = None) -> Optional[Callable[[], Any]]:
    """
    Register the incremental `dsh_session_log` request contribution when enabled.

    @param ctx: plugin context carrying Sessions and the DeepSeek
        request-extension registry.
    @param config: validated opt-in configuration.
    @returns: the extension registration's disposer, or `None` when the
        contribution is disabled.
    """
    enabled = bool((config or {}).get("enabled", False))
    if enabled is not True:
        return None

    extensions = ctx.get("deepseekLlmApiExtensions") if hasattr(ctx, "get") else None
    sessions = ctx.get("sessions") if hasattr(ctx, "get") else None
    if extensions is None or sessions is None:
        raise RuntimeError(
            "session-log-deepseek: the deepseekLlmApiExtensions and sessions services must be mounted"
        )

    def prepare(request: Any) -> Optional[Dict[str, Any]]:
        session_id = _session_id_of(request)
        # TODO: Define an explicit wire result for direct or stale-session calls
        # if they become a supported product path.
        if session_id is None:
            return None
        session = sessions.get(session_id)
        if session is None:
            return None

        after_seq = accepted_through(session)
        snapshot = session.events
        through_seq = len(snapshot) - 1
        if through_seq < 0:
            return None
        value = {
            "version": 1,
            "session": _header_json(session),
            "afterSeq": after_seq,
            "throughSeq": through_seq,
            "events": snapshot[after_seq + 1:],
        }

        def accept() -> None:
            session.append(
                ACCEPTED_EVENT_TYPE, {"sessionId": session.id, "throughSeq": through_seq}
            )
            # TODO: Add an immediate lightweight checkpoint if duplicate replay
            # after a 2xx crash window becomes unacceptable.

        return {"value": value, "accept": accept}

    return extensions.register("dsh_session_log", {"prepare": prepare})


class SessionLogDeepSeekPlugin(Plugin):
    """
    Plugin row `@deepseek-ai/dsh-session-log-deepseek`: the module-level
    contribution, mounted as the installation-owned row.
    """

    id = "session-log-deepseek"
    name = "@deepseek-ai/dsh-session-log-deepseek"
    inject = ["deepseekLlmApiExtensions", "sessions"]

    def apply(self, ctx: Any) -> None:
        apply(ctx, self.config)
