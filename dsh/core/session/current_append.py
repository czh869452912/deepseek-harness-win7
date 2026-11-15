"""Atomic V4 append publication using the store's existing private capability."""
from .json import UNDEFINED, walk_json_value, deep_freeze
from .current import validateSessionEventData
from .session import _attachments, _collect_session_callbacks, _invoke_contained_session_observers


def publication_entry(session):
    entry = _attachments.get(id(session))
    if entry is None and getattr(session, '_store_owned', False):
        raise ValueError('session "%s" cannot append outside a SessionStore' % session.id)
    if entry is not None and not getattr(entry, 'announcement_complete', False):
        raise ValueError('session "%s" cannot append before session/created completes' % session.id)
    if entry is not None and entry.appending:
        raise ValueError('session append cannot reenter while another append is being published')
    return entry


def append_events(session, inputs):
    publication_entry(session)
    if not inputs:
        return []
    snapshots = []
    for index, item in enumerate(inputs):
        if item is None or item is UNDEFINED:
            raise ValueError('session batch has an empty member at index %s' % index)
        kind, data = item[0], item[1] if len(item) > 1 else UNDEFINED
        options = item[2] if len(item) > 2 else {}
        subject = 'session batch member %s ("%s")' % (index, kind)
        payload = walk_json_value(data, detach=True, undefined_sentinel=UNDEFINED)
        if payload is UNDEFINED:
            raise ValueError(subject + ' carries non-JSON-serializable data')
        metadata = {key:options[key] for key in ('sourceEventSeqs', 'surfaceOp')
                    if isinstance(options, dict) and key in options and options[key] is not UNDEFINED}
        metadata = walk_json_value(metadata, detach=True, undefined_sentinel=UNDEFINED)
        if metadata is UNDEFINED:
            raise ValueError(subject + ' carries non-JSON-serializable surface metadata')
        snapshots.append((kind, payload, metadata))
    entry = publication_entry(session)
    start = len(session._log)
    events = []
    for index, (kind, data, metadata) in enumerate(snapshots):
        event = deep_freeze(dict(type=kind,seq=start+index,time=session._event_time(),data=data,**metadata))
        validateSessionEventData(event, 'session event "%s" at seq %s' % (kind,start+index), 4)
        events.append(event)
    accept_surface = session.surface.prepareBatch(events)
    if entry is not None:
        entry.appending = True
    try:
        publications = []
        if entry is not None:
            for event in events:
                args = [session, event]
                callbacks = _collect_session_callbacks(entry.emit_ctx, [entry.carrier, 'session/event', *args])
                publications.append((event, args, callbacks))
        session._log.extend(events)
        session._events_snapshot = None
        accept_surface()
        for event, args, callbacks in publications:
            session._batch_publication = event
            _invoke_contained_session_observers(entry.emit_ctx, 'session/event', entry.id, args, callbacks)
    finally:
        session._batch_publication = UNDEFINED
        if entry is not None:
            entry.appending = False
            if entry.detach_requested:
                entry.detach()
    return events
