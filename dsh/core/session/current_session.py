"""Installed V3 Session with explicit V4 migration admission on the same runtime.

This explicit type lets persistence and Agent consumers migrate as one batch;
the active profile is switched only after its writer and consumers are ready.
"""
import time

from dsh.core.session.session import Session, SessionStore
from dsh.core.session.current import assertSessionEventEnvelope, validateSessionEventData, SURFACE_EVENT_TYPES, V4_SURFACE_EVENT_TYPES, safe
from dsh.core.session.current_surface import CurrentSurfaceManager
from dsh.core.session.current_request_header import foldRequestHeader
from dsh.core.session.json import UNDEFINED, walk_json_value, deep_freeze
from dsh.core.session.types import validate_session_header, SessionLogOffset, SessionId, SessionForkError
from dsh.core.session.lineage import inherited_cut
from dsh.cordis.errors import ThrownValueError
from dsh.session.format_v2_to_v3.payload import display
from .plugin_records import appendPluginRecord, pluginRecordOf


class CurrentSession(Session):
    def __init__(self, session_id, seed=None, header=UNDEFINED, mode='snapshot',
                 ctx=None, inherited_event_count=UNDEFINED, format_version=3, projections=()):
        self.ctx = ctx
        self.format_version = format_version
        self._batch_publication = UNDEFINED
        restored_header = None if mode == 'snapshot' else validate_session_header(session_id, header, expected_version=format_version)
        self._log = []
        self.log = self._log
        self._surface_manager = CurrentSurfaceManager(self._log, format_version=format_version, projections=projections)
        self._events_snapshot = None
        if seed is not None:
            for index, source in enumerate(seed):
                snapshot = walk_json_value(source, detach=True, undefined_sentinel=UNDEFINED) if mode == 'snapshot' else source
                if snapshot is UNDEFINED:
                    raise ValueError('seed event at index %s is not losslessly JSON-serializable' % index)
                assertSessionEventEnvelope(snapshot, index, format_version)
                if snapshot['seq'] != index:
                    raise ValueError('seed event at index %s has seq %s (expected %s); seed must be contiguous from 0' % (index,display(snapshot['seq']),index))
                try:
                    self._surface_manager.validate_next(snapshot)
                except Exception as error:
                    detail = 'invalid surface metadata' if isinstance(error,ThrownValueError) else str(error)
                    raise ValueError('invalid seed event at index %s: %s' % (index,detail)) from None
                self._log.append(deep_freeze(snapshot) if mode == 'snapshot' else snapshot)
        self._first_live_seq = len(self._log)
        if restored_header is not None:
            self.header = restored_header
        else:
            source = dict(version=format_version,id=session_id,createdAt=self._event_time(),isSeeded=False) if header is UNDEFINED else header
            if hasattr(source, 'to_dict'):
                source = source.to_dict()
            snapshot = walk_json_value(source, detach=True, undefined_sentinel=UNDEFINED)
            if snapshot is UNDEFINED:
                raise ValueError('session header is not losslessly JSON-serializable')
            self.header = validate_session_header(session_id, snapshot, expected_version=format_version)
        self._inherited_event_count = inherited_cut(self.header, seed is not None, len(self._log), inherited_event_count)
        cut = self._inherited_event_count
        marker = (cut < len(self._log) and self._log[int(cut)]['type'] == 'session/end-seed'
                  and isinstance(self._log[int(cut)]['data'], dict) and self._log[int(cut)]['data'].get('inherited') is True)
        if mode == 'snapshot' and self.header.isSeeded and cut != len(self._log) and not (format_version == 4 and marker):
            raise ValueError('seeded session constructor seed must equal its inherited prefix' + (' or mark its inherited cut' if format_version == 4 else ''))
        if format_version == 4 and marker and any(event['type'] == 'session/end-seed'
                and isinstance(event['data'], dict) and event['data'].get('inherited') is True for event in self._log[int(cut)+1:]):
            raise ValueError('session inherited event count must identify the final inherited marker')
        self.firstLifecycleSeq = cut if mode == 'snapshot' and self.header.isSeeded else self._first_live_seq
        if seed is not None and mode == 'snapshot' and self.header.isSeeded and not (format_version == 4 and marker):
            self.append('session/end-seed', dict(inherited=True))
        elif seed is not None and not (format_version == 4 and mode == 'snapshot' and self.header.isSeeded) and (not self._log or self._log[-1]['type'] != 'session/end-seed'):
            self.append('session/end-seed', {})
        self._derived, self._derived_nodes, self._derived_generation = [], 0, 0
        self._header_fold, self._header_fold_seq = None, 0
        self._context_fold, self._context_fold_seq = None, 0

    @classmethod
    def from_restore(cls, session_id, seed, header, inherited_event_count, event_state='detached', ctx=None,
                     format_version=3, projections=()):
        # Explicit detached/shared-frozen ownership is a caller promise, not a clone.
        return cls(session_id, seed, header, event_state, ctx, inherited_event_count, format_version, projections)

    fromRestore = from_restore

    @classmethod
    def create(cls, session_id, seed=None, header=UNDEFINED, inherited_event_count=UNDEFINED, ctx=None,
               format_version=3, projections=()):
        return cls(session_id, seed, header, 'snapshot', ctx, inherited_event_count, format_version, projections)

    def _validate_append_data(self, event_type, data):
        pass

    def _validate_append_candidate(self, event):
        if self.format_version == 4:
            from .current_append import publication_entry
            publication_entry(self)
        validateSessionEventData(event, 'session event "%s" at seq %s' % (event['type'],event['seq']), self.format_version)

    @property
    def currentBatchPublication(self):
        return self._batch_publication

    def append(self, event_type, data=UNDEFINED, surface_op=None, source_event_seqs=None, **kwargs):
        if self.format_version == 4:
            from .current_append import publication_entry, append_events
            if not isinstance(event_type, str):
                return append_events(self, event_type)
            publication_entry(self)
        return super().append(event_type, data, surface_op, source_event_seqs, **kwargs)

    def derive_event_message(self, event):
        return self.surface.deriveEventMessage(event)

    deriveEventMessage = derive_event_message

    def derive_messages(self):
        return super().derive_messages()

    deriveMessages = derive_messages

    def request_header(self):
        if self._header_fold_seq < len(self._log):
            self._header_fold = deep_freeze(foldRequestHeader(self._log[self._header_fold_seq:], self._header_fold))
            self._header_fold_seq = len(self._log)
        return self._header_fold

    requestHeader = request_header

    def tool_history(self):
        if not hasattr(self, '_tool_history_projection'):
            from .tool_history import ToolHistoryProjection
            self._tool_history_projection = ToolHistoryProjection()
            self._tool_history_seq = 0
        for event in self._log[self._tool_history_seq:]:
            self._tool_history_projection.apply(event)
        self._tool_history_seq = len(self._log)
        return self._tool_history_projection.snapshot()

    toolHistory = tool_history

    def append_event(self, event_type, data):
        eligible = V4_SURFACE_EVENT_TYPES if self.format_version == 4 else SURFACE_EVENT_TYPES
        return self.append(event_type,data,surface_op='append' if event_type in eligible else None)

    def append_assistant_message(self, *args, **kwargs):
        kwargs.setdefault('stream',[])
        return super().append_assistant_message(*args,**kwargs)

    def fork(self, child_session_id, boundary=None, meta=None):
        # Python convenience over the canonical snapshot constructor.
        cut = self.seq if boundary is None else SessionLogOffset(boundary)
        if cut > self.seq:
            raise ValueError('fork boundary %s out of bounds (0..%s)' % (cut,self.seq))
        values = dict(meta or {})
        values.setdefault('createdAt',self._event_time())
        values.update(version=self.format_version,id=child_session_id)
        values.update(parentSession=self.id,isSeeded=True,delegationDepth=(self.header.delegation_depth or 0)+1)
        if self.header.cwd is not None:
            values.setdefault('cwd',self.header.cwd)
        return type(self).create(child_session_id,self.snapshotEvents(0,cut),values,cut,self.ctx,
                                 self.format_version, self.surface.fold.projections)


class CurrentSessionStore(SessionStore):
    def __init__(self, ctx=None, format_version=3):
        self.format_version = format_version
        self._message_projections = []
        super().__init__(ctx)

    @property
    def messageProjections(self):
        return self._message_projections

    def registerMessageProjection(self, projection):
        if any(item['type'] == projection['type'] for item in self._message_projections):
            raise ValueError('session message projection "%s" is already registered' % projection['type'])
        def setup():
            self._message_projections.append(projection)
            def dispose():
                for index, item in enumerate(self._message_projections):
                    if item is projection:
                        del self._message_projections[index]
                        break
            return dispose
        if self.ctx is None:
            return setup()
        return self.ctx.effect(setup, 'sessions.registerMessageProjection()')

    def prepare(self, session_id=None, options=None, **kwargs):
        opts = dict(options or {})
        opts.update(kwargs)
        if session_id is None:
            while True:
                self._counter += 1
                sid = SessionId('session-%s' % self._counter)
                if sid not in self._entries:
                    break
        else:
            sid = SessionId(session_id)
        if sid in self._entries:
            raise ValueError('session "%s" already exists' % sid)
        state = opts.get('eventState', UNDEFINED)
        if state in ('detached', 'shared-frozen'):
            session = CurrentSession.from_restore(sid, opts['seed'], opts['meta'], opts['inheritedEventCount'], state, self.ctx,
                                                 self.format_version, self._message_projections)
            if self.format_version == 4:
                session._store_owned = True
            return session
        if state is not UNDEFINED:
            raise ValueError('SessionStore.prepare event state: ' + display(state))
        meta = opts.get('meta') or {}
        header = dict(version=self.format_version,id=sid,createdAt=meta.get('createdAt') if meta.get('createdAt') is not None else int(time.time()*1000),
                      isSeeded=False if meta.get('isSeeded') is None else meta['isSeeded'])
        for key in ('cwd','parentSession','origin','delegationDepth','agentPreset'):
            if key in meta and meta[key] is not UNDEFINED:
                header[key] = meta[key]
        session = CurrentSession.create(sid, opts.get('seed'), header, opts.get('inheritedEventCount', UNDEFINED), self.ctx,
                                        self.format_version, self._message_projections)
        if self.format_version == 4:
            session._store_owned = True
        return session

    def enter(self, session):
        dispose = super().enter(session)
        if self.format_version == 4:
            session._store_owned = True
        return dispose

    def announce(self, session):
        if self.format_version != 4:
            return super().announce(session)
        entry = self._live_entry_for(session)
        super().announce(session)
        entry.announcement_complete = True

    def fork(self, source, boundary=None, child_session_id=None):
        if self.format_version != 4:
            return super().fork(source, boundary, child_session_id)
        from dsh.core.session.fork import build_fork_seed
        if child_session_id is not None and self.get(child_session_id) is not None:
            raise SessionForkError('session "%s" already exists' % child_session_id, 'SESSION_ALREADY_EXISTS')
        live = self._resolve_fork_source(source)
        events = live.snapshotEvents()
        resolved = boundary if boundary is not None else events[-1]['seq'] if events else None
        if resolved is not None:
            if not safe(resolved, True):
                raise SessionForkError('fork boundary for session "%s" must be a non-negative safe integer, got %s' %
                    (live.id, display(resolved)), 'INVALID_BOUNDARY')
            if resolved >= len(events):
                raise SessionForkError('fork boundary %s does not exist in session "%s" (last seq: %s)' %
                    (display(resolved), live.id, display(events[-1]['seq']) if events else 'none'), 'INVALID_BOUNDARY')
            if events[int(resolved)]['seq'] != resolved:
                raise SessionForkError('fork boundary %s does not match a contiguous event seq in session "%s"' %
                    (display(resolved), live.id), 'INVALID_BOUNDARY')
        meta = dict(isSeeded=True)
        if live.header.cwd is not None:
            meta['cwd'] = live.header.cwd
        return self.create(child_session_id, dict(seed=[] if resolved is None else build_fork_seed(events, resolved),
            inheritedEventCount=0 if resolved is None else resolved+1, meta=meta))

    def _fork_seed(self, session, requested_boundary):
        events=session.snapshotEvents()
        if requested_boundary is None:
            if not events:
                return []
            boundary=events[-1]['seq']
        else:
            boundary=requested_boundary
        if not safe(boundary,True):
            raise SessionForkError('fork boundary for session "%s" must be a non-negative safe integer, got %s' %
                (session.id,display(boundary)),'INVALID_BOUNDARY')
        if boundary>=session.seq:
            raise SessionForkError('fork boundary %s does not exist in session "%s" (last seq: %s)' %
                (display(boundary),session.id,display(events[-1]['seq']) if events else 'none'),'INVALID_BOUNDARY')
        event=session.eventAt(boundary)
        if event is UNDEFINED or event['seq']!=boundary:
            raise SessionForkError('fork boundary %s does not match a contiguous event seq in session "%s"' %
                (display(boundary),session.id),'INVALID_BOUNDARY')
        prefix=session.snapshotEvents(0,boundary+1)
        last=next((event for event in reversed(prefix) if event['type'] in ('turn/start','turn/end')),None)
        if last is not None and last['type']=='turn/start':
            raise SessionForkError('fork boundary %s in session "%s" ends inside open turn %s' %
                (display(boundary),session.id,display(last['data']['turn'])),'OPEN_TURN')
        return prefix


from dsh.cordis.plugin import Plugin


class CurrentSessionPlugin(Plugin):
    id = 'session'
    name = '@deepseek-ai/dsh-session'

    def apply(self, ctx):
        ctx.set_service('sessions',CurrentSessionStore(ctx))
