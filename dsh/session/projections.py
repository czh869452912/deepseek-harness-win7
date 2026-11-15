"""Pinned session projection drive; keyword registration adapts older domains."""
import asyncio
import copy
import inspect
import math
from typing import Any, Callable, Dict, Optional
from weakref import WeakKeyDictionary

from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.core.session import snapshot_json_value
from dsh.core.session.json import UNDEFINED
from dsh.core.session.types import SessionLogOffset
from dsh.cordis.json_text import stringify_json
from dsh.session.format_v2_to_v3.payload import display


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
        self.views = [UNDEFINED, UNDEFINED]


class Registration:
    def __init__(self, definition, legacy=None):
        self.definition = definition
        self.legacy = legacy
        self.cells = WeakKeyDictionary()
        self.refs = 1


class ProjectionHandle:
    def __init__(self, registry, registration, release):
        self._registry, self._registration, self._release = registry, registration, release

    def stateOf(self, session):
        return self._registry._cell(self._registration,session).state

    state_of = stateOf

    def readerFor(self, session):
        return lambda:self.stateOf(session)

    reader_for = readerFor

    async def dispose(self):
        result = self._release()
        if inspect.isawaitable(result):
            await result


class ProjectionRegistration:
    """Python awaitable/callable counterpart of the Source callable thenable."""
    def __init__(self, owner, release, registration, registry, error=None):
        self._release, self._observed = release, False
        async def ready():
            # Setup has already run synchronously, as it does before the
            # Source acquire() reaches its Promise.resolve() handoff.
            await asyncio.sleep(0)
            if error is not None:
                raise error
            if owner is not None:
                owner.fiber.assert_active()
            return ProjectionHandle(registry,registration,release)
        self._ready = asyncio.ensure_future(ready())
        def finished(task):
            if task.cancelled():
                return
            failure = task.exception()
            if failure is None or owner is None:
                return
            def report():
                from dsh.cordis.fiber import FiberState
                if not self._observed and owner.fiber.state in (FiberState.LOADING,FiberState.ACTIVE):
                    owner.logger.error(failure)
            task.get_loop().call_later(0,report)
        self._ready.add_done_callback(finished)

    def __call__(self):
        return self._release()

    def __await__(self):
        self._observed = True
        return asyncio.shield(self._ready).__await__()


class SessionProjectionRegistry(Service):
    def __init__(self, ctx: Optional[Any] = None, format_version=3):
        self.format_version = format_version
        self._registrations: Dict[str, Registration] = {}
        self._listeners: Dict[Callable, None] = {}
        self._event_listeners = {}
        self._summary_keys = None
        self._deprecated_keys = set()
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
                              init=lambda header, inherited_event_count: init(), apply=apply,
                              stateVersion=state_version)
            if view is not None:
                definition["wire"] = dict(view=view, viewSchema=lambda value: value)
        if self.format_version == 4:
            return self._register_current(definition,legacy)
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

    def _register_current(self, definition, legacy):
        owner = self.ctx
        registration, error = None, None
        release = lambda:None
        try:
            key, version = definition['key'], definition['stateVersion']
            wire = definition.get('wire')
            erased = dict(key=key,stateVersion=version,stateSchema=definition['stateSchema'],
                init=lambda header,cut:definition['init'](header,cut),apply=lambda state,event:definition['apply'](state,event))
            if wire is not None:
                erased['wire'] = dict(viewSchema=wire['viewSchema'],view=lambda state:wire['view'](state),summary=wire.get('summary') is not False)
            if type(version) not in (int,float) or not 0 <= version <= 9007199254740991 or int(version) != version:
                raise ValueError('session projection %s stateVersion must be a non-negative integer, got %s' % (stringify_json(key),display(version)))
            def setup():
                nonlocal registration
                existing = self._registrations.get(key)
                if existing is None or existing.refs == 0:
                    registration = Registration(erased,legacy)
                    self._registrations[key] = registration
                    self._summary_keys = None
                else:
                    old = existing.definition
                    if old['stateVersion'] != version:
                        raise ValueError('session projection key %s is already registered at stateVersion %s; refusing to share it with stateVersion %s' %
                            (stringify_json(key),display(old['stateVersion']),display(version)))
                    before = old.get('wire',{}).get('summary',UNDEFINED)
                    after = erased.get('wire',{}).get('summary',UNDEFINED)
                    if before is not after:
                        raise ValueError('session projection key %s is already registered with summary=%s; refusing to share it with summary=%s' %
                            (stringify_json(key),display(before),display(after)))
                    existing.refs += 1
                    registration = existing
                def remove():
                    registration.refs -= 1
                    if registration.refs == 0:
                        self._summary_keys = None
                return remove
            release = self._effect(setup,'sessionProjections.register()')
        except Exception as failure:
            error = failure
        ready = ProjectionRegistration(owner,release,registration,self,error)
        if owner is not None and error is None:
            # Keep the exact effect disposer: composing effects transfer its
            # identity and metadata out of the fiber's disposal list. Python
            # special methods live on types, so give this one object an await
            # override instead of returning a second disposer identity.
            release.__class__ = type('ProjectionEffect',(type(release),),{
                '__await__':lambda disposer:ready.__await__()})
            return release
        return ready

    def _live_registrations(self):
        return [(key,registration) for key,registration in self._registrations.items() if registration.refs > 0]

    def has(self, key):
        return key in self._registrations and self._registrations[key].refs > 0

    def get_unit(self, key):
        registration = self._registrations.get(key)
        return None if registration is None or registration.refs == 0 else registration.legacy or registration.definition

    def on_change(self, listener):
        def setup():
            self._listeners[listener] = None
            return lambda: self._listeners.pop(listener, None)
        return self._effect(setup, "sessionProjections.onChanged()")

    onChanged = on_change

    def onEventChanged(self, listener):
        def setup():
            self._event_listeners[listener] = None
            return lambda:self._event_listeners.pop(listener,None)
        return self._effect(setup,'sessionProjections.onEventChanged()')

    def summaryKeys(self):
        if self._summary_keys is None:
            self._summary_keys = {key for key,registration in self._live_registrations()
                if registration.definition.get('wire') is not None and registration.definition['wire'].get('summary',True)}
        return self._summary_keys

    def on_session_created(self, session):
        if session.seq == 0:
            for registration in self._registrations.values():
                if registration.refs == 0:
                    continue
                if session not in registration.cells:
                    registration.cells[session] = UnitCell(registration.definition["init"](
                        session.header, session.inheritedEventCount))

    def _build(self, definition, header, events, inherited_event_count):
        state = definition["init"](header, inherited_event_count)
        for event in events:
            state = definition["apply"](state, event)
        return UnitCell(state, events[-1]["seq"] if events else -1)

    def _advance(self, definition, cell, events, through):
        # JSON/SQLite decode JS numbers as floats. Validate the integer domain
        # before converting positions for Python's range/slice operations.
        for seq in range(int(SessionLogOffset(cell.observed_seq + 1)), int(SessionLogOffset(through + 1))):
            if seq >= len(events) or events[seq]["seq"] != seq:
                raise ValueError('session projection %r cannot advance across missing seq %s' % (definition["key"], seq))
            state = definition["apply"](cell.state, events[seq])
            if not _same(state, cell.state):
                cell.views = [cell.views[1], UNDEFINED]
            cell.state = state
            cell.observed_seq = seq

    def _cell(self, registration, session):
        cell = registration.cells.get(session)
        if cell is None:
            cell = self._build(registration.definition, session.header, session.events, session.inheritedEventCount)
            registration.cells[session] = cell
        else:
            self._advance(registration.definition, cell, session.events, session.seq - 1)
        return cell

    def _materialize(self, session):
        for _,registration in self._live_registrations():
            self._cell(registration, session)

    def _view(self, registration, cell):
        wire = registration.definition["wire"]
        return _parse(wire["viewSchema"], wire["view"](cell.state))

    def on_session_event(self, session, event):
        if self.format_version == 4:
            return self._drive_current(session,event)
        for registration in list(self._registrations.values()):
            cell = registration.cells.get(session)
            seq = int(SessionLogOffset(event["seq"]))
            if cell is not None and cell.observed_seq >= seq:
                continue
            if cell is None:
                cell = self._build(registration.definition, session.header, session.events[:seq], session.inheritedEventCount)
                registration.cells[session] = cell
            else:
                self._advance(registration.definition, cell, session.events, seq - 1)
            state = registration.definition["apply"](cell.state, event)
            changed = not _same(state, cell.state)
            cell.state, cell.observed_seq = state, seq
            wire = registration.definition.get("wire")
            if changed and wire is not None:
                cell.views[0] = cell.views[1]
                if self._listeners:
                    cell.views[1] = wire["view"](state)
                    if not _same(cell.views[0], cell.views[1]):
                        value = _parse(wire["viewSchema"], cell.views[1])
                        for listener in list(self._listeners):
                            listener(session, registration.definition["key"], value, seq)
                else:
                    cell.views[1] = UNDEFINED

    def _drive_current(self, session, event):
        observed = bool(self._listeners or self._event_listeners)
        changes = []
        visited = set()
        try:
            while True:
                key = next((key for key in self._registrations if key not in visited),UNDEFINED)
                if key is UNDEFINED:
                    break
                visited.add(key)
                registration = self._registrations[key]
                if registration.refs == 0:
                    continue
                cell = registration.cells.get(session)
                seq = int(SessionLogOffset(event['seq']))
                if cell is not None and cell.observed_seq >= seq:
                    continue
                if cell is None:
                    cell = self._build(registration.definition,session.header,session.events[:seq],session.inheritedEventCount)
                    registration.cells[session] = cell
                else:
                    self._advance(registration.definition,cell,session.events,seq-1)
                state = registration.definition['apply'](cell.state,event)
                changed = not _same(state,cell.state)
                cell.state,cell.observed_seq = state,seq
                wire = registration.definition.get('wire')
                if changed and wire is not None:
                    cell.views[0] = cell.views[1]
                    if observed:
                        cell.views[1] = wire['view'](state)
                        if not _same(cell.views[0],cell.views[1]):
                            value = _parse(wire['viewSchema'],cell.views[1])
                            changes.append(dict(key=key,val=value))
                            for listener in list(self._listeners):
                                listener(session,key,value,seq)
                    else:
                        cell.views[1] = UNDEFINED
        finally:
            if changes:
                for listener in list(self._event_listeners):
                    listener(session,changes,seq)

    def state_of(self, session, key):
        if self.format_version == 4 and key not in self._deprecated_keys:
            self._deprecated_keys.add(key)
            if self.ctx is not None:
                self.ctx.logger.warn('sessionProjections.stateOf(session, %s) is deprecated; read handle.stateOf(session) from an awaited registration, or use the owning domain service' % stringify_json(key))
        registration = self._registrations.get(key)
        if registration is None or registration.refs == 0:
            return UNDEFINED if self.format_version == 4 else None
        self._materialize(session)
        return self._cell(registration, session).state

    stateOf = state_of

    def snapshot(self, session, keys=None):
        if self.format_version != 4:
            self._materialize(session)
        values = {}
        for key, registration in self._live_registrations():
            if registration.definition.get("wire") is not None and (keys is None or key in keys):
                values[key] = self._view(registration, self._cell(registration, session))
        return {"asOfSeq": session.seq - 1, "values": values}

    def cached_snapshot(self, session, keys=None):
        values, watermarks = {}, []
        for key, registration in self._live_registrations():
            cell = registration.cells.get(session)
            if cell is not None and registration.definition.get("wire") is not None and (keys is None or key in keys):
                values[key] = self._view(registration, cell)
                watermarks.append(cell.observed_seq)
        return {"asOfSeq": min(watermarks), "values": values} if watermarks else None

    cachedSnapshot = cached_snapshot

    def checkpoint(self, session):
        rows = {}
        for key, registration in self._registrations.items():
            cell = registration.cells.get(session) if registration.refs == 0 else self._cell(registration, session)
            if cell is None:
                continue
            invalid = object()
            value = snapshot_json_value(cell.state, default=invalid)
            if value is invalid:
                # Keep non-JSON state visible for the cache's lossless boundary;
                # converting a bad state to null would persist a false value.
                value = copy.deepcopy(cell.state)
            rows[key] = dict(ver=registration.definition["stateVersion"],
                             seq=cell.observed_seq, val=value)
        return rows

    def restore_floor(self, checkpoint):
        floor = None
        for key, registration in self._live_registrations():
            row = checkpoint.get(key)
            need = max(row["seq"] + 1, 0) if row is not None and row["ver"] == registration.definition["stateVersion"] else 0
            floor = need if floor is None else min(floor, need)
        return None if floor is None else max(floor - 1, 0)

    restoreFloor = restore_floor

    def view_checkpoint(self, checkpoint, keys=None):
        values = {}
        for key, registration in self._live_registrations():
            definition = registration.definition
            if definition.get("wire") is None or (keys is not None and key not in keys):
                continue
            row = checkpoint.get(key)
            if row is None or row["ver"] != definition["stateVersion"]:
                continue
            try:
                state = _parse(definition["stateSchema"], row["val"])
            except Exception:
                continue
            values[key] = self._view(registration, UnitCell(state))
        return values

    viewCheckpoint = view_checkpoint

    def restore(self, checkpoint, events, base_seq, header, inherited_event_count=UNDEFINED):
        if inherited_event_count is UNDEFINED:
            seeded = header.get('isSeeded', False) if isinstance(header, dict) else getattr(header, 'isSeeded', False)
            if seeded is True:
                raise ValueError('seeded projection restore requires an inherited event count')
            inherited_event_count = 0
        end_seq = events[-1]["seq"] if events else base_seq - 1
        values, refreshed = {}, {}
        for key, registration in self._live_registrations():
            definition = registration.definition
            row = checkpoint.get(key)
            usable = (row is not None and row["ver"] == definition["stateVersion"]
                      and base_seq - 1 <= row["seq"] <= end_seq)
            if not usable and base_seq > 0:
                raise ValueError('session projection %r cannot restore from seq %s: '
                                 'its checkpoint row is missing, version-mismatched, or beyond '
                                 'the supplied log end; re-read from seq 0' % (key, base_seq))
            state = (_parse(definition["stateSchema"], row["val"]) if usable
                     else definition["init"](header, inherited_event_count))
            start = int(SessionLogOffset(row["seq"] - base_seq + 1)) if usable else 0
            for index in range(start, len(events)):
                event = events[index]
                if event is None or event["seq"] != base_seq + index:
                    raise ValueError('session projection %r cannot restore across missing seq %s' % (key, base_seq + index))
                state = definition["apply"](state, event)
            if definition.get("wire") is not None:
                values[key] = self._view(registration, UnitCell(state))
            refreshed[key] = dict(ver=definition["stateVersion"], seq=end_seq, val=state)
        return dict(snapshot=dict(asOfSeq=end_seq, values=values), checkpoint=refreshed)

    def hydrate(self, session, checkpoint, events, base_seq):
        end_seq = events[-1]["seq"] if events else base_seq - 1
        if all(session in registration.cells and registration.cells[session].observed_seq == end_seq
               for _,registration in self._live_registrations()):
            return dict(asOfSeq=end_seq, values={
                key: self._view(registration, registration.cells[session])
                for key, registration in self._live_registrations()
                if registration.definition.get("wire") is not None})
        restored = self.restore(checkpoint, events, base_seq, session.header, session.inheritedEventCount)
        for key, registration in self._live_registrations():
            row = restored["checkpoint"][key]
            current = registration.cells.get(session)
            if current is None or current.observed_seq <= row["seq"]:
                registration.cells[session] = UnitCell(row["val"], row["seq"])
        return restored["snapshot"]


class SessionProjectionsPlugin(Plugin):
    id = "session-projection"
    name = "@deepseek-ai/dsh-session-projection"

    def apply(self, ctx):
        registry = SessionProjectionRegistry(ctx)
        # Existing Web carrier consumes this adapter until its own migration.
        registry.onChanged(lambda session, key, value, seq: ctx.emit("projection/change", {
            "sessionId": session.id, "key": key, "value": value, "seq": seq,
        }))
