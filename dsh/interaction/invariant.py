"""
Package-owned invariant companion for `@deepseek-ai/dsh-commands`: command
lifecycle events pair by commandId within one session log.
1:1 with reference/packages/interaction/commands/src/invariant.ts.
Python 3.8.10 compatible.
"""

import json
from typing import Any, Callable, Dict, Optional, Set

PACKAGE_NAME = "@deepseek-ai/dsh-commands"
name = "commands-invariant"
inject = ["invariants"]


def install(ctx: Any, fail: Callable[[str], None]) -> None:
    """
    Install pairing validation over loaded logs and newly appended lifecycle
    events. Install-scoped, so a dispose/re-register cycle re-sweeps from a
    clean slate.
    """
    run_ids: Dict[Any, Set[Any]] = {}

    def validate_event(session: Any, event: Any) -> None:
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event_type == "command/run":
            ids = run_ids.setdefault(session, set())
            command_id = data.get("commandId")
            if command_id in ids:
                fail("command/run repeats commandId {}".format(json.dumps(command_id)))
            ids.add(command_id)
            return
        if event_type != "command/done":
            return
        command_id = data.get("commandId")
        if command_id not in run_ids.get(session, set()):
            fail(
                "command/done {} pairs no prior command/run in this log".format(
                    json.dumps(command_id)
                )
            )
        source = data.get("sourceEventSeq")
        if source is None:
            return
        events = getattr(session, "events", [])
        source_event = (
            events[source] if isinstance(source, int) and 0 <= source < len(events) else None
        )
        source_type = source_event.get("type") if isinstance(source_event, dict) else None
        source_seq = source_event.get("seq") if isinstance(source_event, dict) else None
        seq = event.get("seq", 0)
        if (
            data.get("kind") != "success"
            or not isinstance(source, int)
            or isinstance(source, bool)
            or source < 0
            or not isinstance(seq, int)
            or source >= seq
            or source_seq != source
            or source_type in ("command/run", "command/done")
        ):
            fail(
                "command/done {} has invalid sourceEventSeq {}".format(
                    json.dumps(command_id), str(source)
                )
            )

    sessions = ctx.sessions if hasattr(ctx, "sessions") else ctx.get("sessions")
    if sessions is not None and hasattr(sessions, "list"):
        for session in sessions.list():
            for event in list(getattr(session, "events", [])):
                validate_event(session, event)

    if hasattr(ctx, "on"):
        def on_dispatch(
            mode: Any, event_name: Any, args: Any, *extra: Any
        ) -> None:
            if event_name != "session/event":
                return
            validate_event(args[0], args[1])

        ctx.on("internal/dispatch", on_dispatch, global_listener=True)


#: The reference's `Object.assign(install, { inject: ['sessions'] })`.
install.inject = ["sessions"]


def apply(ctx: Any) -> Optional[Any]:
    invariants_svc = ctx.get("invariants") if hasattr(ctx, "get") else None
    if invariants_svc is not None and hasattr(invariants_svc, "register"):
        return registration_result(invariants_svc.register(PACKAGE_NAME, install))
    return None


from dsh.diagnostics.invariants import registration_result
