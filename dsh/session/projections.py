"""Pinned session projection drive; keyword registration adapts older domains."""
import math
from typing import Any, Callable, Dict, Optional
from weakref import WeakKeyDictionary

from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


def _parse(schema, value):
    parser = getattr(schema, "parse", None)
    if parser is not None:
        return parser(value)
    if callable(schema):
        return schema(value)
    raise TypeError("projection schema must expose parse(value) or be a parser")


def _same(a, b):
    """Object.is for JSON states, including numeric NaN and signed zero."""
    if type(a) in (int, float) and type(b) in (int, float):
        if math.isnan(a) and math.isnan(b):
            return True
        if a == b == 0:
            return math.copysign(1, a) == math.copysign(1, b)
        return a == b
    if type(a) in (str, bool, type(None)):
        return type(a) is type(b) and a == b
    return a is b


class ProjectionDefinition:
    """Compatibility view exposed to existing Python domain consumers."""
    def __init__(self, key, schema, init, apply, view, state_version=1):
        self.key, self.schema, self.init = key, schema, init
        self.apply, self.view, self.state_version = apply, view, state_version


class UnitCell:
    def __init__(self, state, observed_seq=-1):
        self.state, self.observed_seq = state, observed_seq


class Registration:
    def __init__(self, definition, legacy=None):
        self.definition = definition
        self.legacy = legacy
        self.cells = WeakKeyDictionary()
        self.refs = 1


class SessionProjectionRegistry(Service):
    def __init__(self, ctx: Optional[Any] = None):
        self._registrations: Dict[str, Registration] = {}
        self._listeners: Dict[Callable, None] = {}
        super().__init__(ctx, "sessionProjections")
        if ctx is not None:
            ctx.on("session/created", self.on_session_created)
            ctx.on("session/event", self.on_session_event)

    def _effect(self, setup, label):
        if self.ctx is not None:
            return self.ctx.effect(setup, label=label)
        dispose = setup()
        active = True

        def once():
            nonlocal active
            if active:
                active = False
                dispose()
        return once

    def register(self, definition=None, *, key=None, schema=None, init=None,
                 apply=None, view=None, state_version=1):
        legacy = None
        if definition is None:
            legacy = ProjectionDefinition(key, schema, init, apply, view, state_version)
            # Older domains supplied descriptive JSON schemas, not state parsers.
            # Canonical definitions below always use their executable parsers.
            definition = dict(key=key, stateSchema=lambda value: value,
                              init=lambda header: init(), apply=apply,
                              stateVersion=state_version)
            if view is not None:
                definition["wire"] = dict(view=view, viewSchema=lambda value: value)
        definition = dict(definition)
        key, version = definition["key"], definition["stateVersion"]
        if type(version) is not int or not 0 <= version <= 9007199254740991:
            raise ValueError('session projection %r stateVersion must be a non-negative integer' % key)

        def setup():
            registration = self._registrations.get(key)
            if registration is None:
                registration = Registration(definition, legacy)
                self._registrations[key] = registration
            else:
                if registration.definition["stateVersion"] != version:
                    raise ValueError('session projection key %r is already registered at another stateVersion' % key)
                registration.refs += 1

            def remove():
                registration.refs -= 1
                if registration.refs == 0:
                    self._registrations.pop(key, None)
            return remove
        return self._effect(setup, "sessionProjections.register()")

    def has(self, key):
        return key in self._registrations

    def get_unit(self, key):
        registration = self._registrations.get(key)
        return None if registration is None else registration.legacy or registration.definition

    def on_change(self, listener):
        def setup():
            self._listeners[listener] = None
            return lambda: self._listeners.pop(listener, None)
        return self._effect(setup, "sessionProjections.onChanged()")

    onChanged = on_change

    def on_session_created(self, session):
        if session.seq == 0:
            for registration in self._registrations.values():
                if session not in registration.cells:
                    registration.cells[session] = UnitCell(registration.definition["init"](session.header))

    def _build(self, definition, header, events):
        state = definition["init"](header)
        for event in events:
            state = definition["apply"](state, event)
        return UnitCell(state, events[-1]["seq"] if events else -1)

    def _advance(self, definition, cell, events, through):
        for seq in range(cell.observed_seq + 1, through + 1):
            if seq >= len(events) or events[seq]["seq"] != seq:
                raise ValueError('session projection %r cannot advance across missing seq %s' % (definition["key"], seq))
            cell.state = definition["apply"](cell.state, events[seq])
            cell.observed_seq = seq

    def _cell(self, registration, session):
        cell = registration.cells.get(session)
        if cell is None:
            cell = self._build(registration.definition, session.header, session.events)
            registration.cells[session] = cell
        else:
            self._advance(registration.definition, cell, session.events, session.seq - 1)
        return cell

    def _materialize(self, session):
        for registration in self._registrations.values():
            self._cell(registration, session)

    def _view(self, registration, cell):
        wire = registration.definition["wire"]
        return _parse(wire["viewSchema"], wire["view"](cell.state))

    def on_session_event(self, session, event):
        for registration in list(self._registrations.values()):
            cell = registration.cells.get(session)
            seq = event["seq"]
            if cell is not None and cell.observed_seq >= seq:
                continue
            if cell is None:
                cell = self._build(registration.definition, session.header, session.events[:seq])
                registration.cells[session] = cell
            else:
                self._advance(registration.definition, cell, session.events, seq - 1)
            state = registration.definition["apply"](cell.state, event)
            changed = not _same(state, cell.state)
            cell.state, cell.observed_seq = state, seq
            if changed and registration.definition.get("wire") is not None and self._listeners:
                value = self._view(registration, cell)
                for listener in list(self._listeners):
                    listener(session, registration.definition["key"], value, seq)

    def state_of(self, session, key):
        registration = self._registrations.get(key)
        if registration is None:
            return None
        self._materialize(session)
        return self._cell(registration, session).state

    stateOf = state_of

    def snapshot(self, session, keys=None):
        self._materialize(session)
        values = {}
        for key, registration in self._registrations.items():
            if registration.definition.get("wire") is not None and (keys is None or key in keys):
                values[key] = self._view(registration, self._cell(registration, session))
        return {"asOfSeq": session.seq - 1, "values": values}

    def cached_snapshot(self, session, keys=None):
        values, watermarks = {}, []
        for key, registration in self._registrations.items():
            cell = registration.cells.get(session)
            if cell is not None and registration.definition.get("wire") is not None and (keys is None or key in keys):
                values[key] = self._view(registration, cell)
                watermarks.append(cell.observed_seq)
        return {"asOfSeq": min(watermarks), "values": values} if watermarks else None

    cachedSnapshot = cached_snapshot


class SessionProjectionsPlugin(Plugin):
    id = "session-projection"
    name = "@deepseek-ai/dsh-session-projection"

    def apply(self, ctx):
        registry = SessionProjectionRegistry(ctx)
        # Existing Web carrier consumes this adapter until its own migration.
        registry.onChanged(lambda session, key, value, seq: ctx.emit("projection/change", {
            "sessionId": session.id, "key": key, "value": value, "seq": seq,
        }))
