"""
Package-owned session-event invariants for the sandbox policy.

1:1 with reference/packages/sandbox/sandbox-policy/src/invariant.ts: every
durable `sandbox/mode` event must carry a mode from the closed three-way
vocabulary, checked both over already-loaded history and over newly appended
events.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Callable, Optional

from dsh.sandbox.vocabulary import SANDBOX_MODES

PACKAGE_NAME = "@deepseek-ai/dsh-sandbox-policy"
name = "sandbox-policy-invariant"
inject = ["invariants"]

MODE_EVENT_TYPE = "sandbox/mode"


def _validate_event(event: Any, fail: Callable[[str], None]) -> None:
    """Validate the package-owned event fields and ignore unrelated events."""
    if not isinstance(event, dict) or event.get("type") != MODE_EVENT_TYPE:
        return
    mode = (event.get("data") or {}).get("mode")
    if mode not in SANDBOX_MODES:
        fail("sandbox/mode carries unknown mode {}".format(_json(mode)))


def _json(value: Any) -> str:
    """`JSON.stringify` for the failure message."""
    import json

    return json.dumps(value)


def install(ctx: Any, fail: Callable[[str], None]) -> None:
    """Install validation for loaded and newly appended sandbox modes."""
    sessions = ctx.sessions if hasattr(ctx, "sessions") else ctx.get("sessions")
    if sessions is not None and hasattr(sessions, "list"):
        for session in sessions.list():
            for event in list(getattr(session, "events", [])):
                _validate_event(event, fail)

    if hasattr(ctx, "on"):

        def on_dispatch(mode: Any, event_name: Any, args: Any, *_extra: Any) -> None:
            if event_name != "session/event":
                return
            event = args[1] if len(args) > 1 else None
            _validate_event(event, fail)

        ctx.on("internal/dispatch", on_dispatch, global_listener=True)


#: The reference's `Object.assign(install, { inject: ['sessions'] })`.
install.inject = ["sessions"]


def apply(ctx: Any) -> Optional[Any]:
    """Register this package's invariant companion."""
    registry = ctx.get("invariants") if hasattr(ctx, "get") else None
    if registry is not None and hasattr(registry, "register"):
        return registration_result(registry.register(PACKAGE_NAME, install))
    return None


from dsh.diagnostics.invariants import registration_result
