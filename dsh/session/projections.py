"""
Session Projections Seam (`@deepseek-ai/dsh-session-projection`).
Provides state-driven event-sourced projections over committed session events.
"""

from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.core.session import Session


class ProjectionDefinition:
    """Definition of a single session projection unit."""

    def __init__(
        self,
        key: str,
        schema: Any,
        init: Callable[[], Any],
        apply: Callable[[Any, Any], Any],
        view: Callable[[Any], Any],
        state_version: int = 1,
    ):
        self.key = key
        self.schema = schema
        self.init = init
        self.apply = apply
        self.view = view
        self.state_version = state_version


class UnitCell:
    """Per-session per-unit state cell."""

    def __init__(self, state: Any, observed_seq: int = -1):
        self.state = state
        self.observed_seq = observed_seq


class SessionProjectionRegistry:
    """
    Registry for session projections (`ctx.sessionProjections`).
    Drives projection units eagerly over committed session events.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx
        self._units: Dict[str, ProjectionDefinition] = {}
        self._cells: Dict[str, Dict[str, UnitCell]] = {}
        self._listeners: List[Callable[[Session, str, Any, int], None]] = []

    def register(
        self,
        key: str,
        schema: Any,
        init: Callable[[], Any],
        apply: Callable[[Any, Any], Any],
        view: Callable[[Any], Any],
        state_version: int = 1,
    ) -> Callable[[], None]:
        unit = ProjectionDefinition(
            key=key,
            schema=schema,
            init=init,
            apply=apply,
            view=view,
            state_version=state_version,
        )
        self._units[key] = unit
        if key not in self._cells:
            self._cells[key] = {}

        def unregister() -> None:
            self._units.pop(key, None)
            self._cells.pop(key, None)

        return unregister

    def has(self, key: str) -> bool:
        return key in self._units

    def get_unit(self, key: str) -> Optional[ProjectionDefinition]:
        return self._units.get(key)

    def on_change(self, listener: Callable[[Session, str, Any, int], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _get_cell(self, session: Session, key: str) -> UnitCell:
        sess_id = getattr(session, "id", str(id(session)))
        unit = self._units.get(key)
        if not unit:
            raise KeyError(f"Unknown projection key: {key}")

        if key not in self._cells:
            self._cells[key] = {}

        if sess_id not in self._cells[key]:
            self._cells[key][sess_id] = UnitCell(state=unit.init(), observed_seq=-1)

        return self._cells[key][sess_id]

    def on_session_event(self, session: Session, event: Any) -> None:
        seq = event.get("seq", 0) if isinstance(event, dict) else getattr(event, "seq", 0)
        for key, unit in list(self._units.items()):
            cell = self._get_cell(session, key)
            old_state = cell.state
            new_state = unit.apply(old_state, event)
            cell.observed_seq = seq

            if new_state is not old_state:
                cell.state = new_state
                view_val = unit.view(new_state)
                for listener in list(self._listeners):
                    try:
                        listener(session, key, view_val, seq)
                    except Exception:
                        pass
                if self.ctx and hasattr(self.ctx, "emit"):
                    self.ctx.emit("projection/change", {
                        "sessionId": getattr(session, "id", None),
                        "key": key,
                        "value": view_val,
                        "seq": seq,
                    })

    def snapshot(self, session: Session) -> Dict[str, Any]:
        as_of_seq = -1
        values: Dict[str, Any] = {}

        events = getattr(session, "events", [])
        for key, unit in self._units.items():
            cell = self._get_cell(session, key)
            if cell.observed_seq < len(events) - 1:
                current_state = cell.state
                for i in range(cell.observed_seq + 1, len(events)):
                    evt = events[i]
                    current_state = unit.apply(current_state, evt)
                cell.state = current_state
                cell.observed_seq = len(events) - 1

            as_of_seq = max(as_of_seq, cell.observed_seq)
            values[key] = unit.view(cell.state)

        return {
            "asOfSeq": as_of_seq,
            "values": values,
        }


class SessionProjectionsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-projection`: Registers sessionProjections service.
    """

    id = "session-projection"
    name = "@deepseek-ai/dsh-session-projection"

    def apply(self, ctx: Any) -> None:
        registry = SessionProjectionRegistry(ctx)
        ctx.set_service("sessionProjections", registry)

        ctx.on("session/event", lambda session, event: registry.on_session_event(session, event))
