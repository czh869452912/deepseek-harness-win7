"""Experimental durable records, outside the model-visible event vocabulary."""
import re

from dsh.cordis.utils import js_to_string
from .current_append import publication_entry
from .json import UNDEFINED, walk_json_value, deep_freeze
from .session import _collect_session_callbacks, _invoke_contained_session_observers

_RECORD_TYPE = re.compile(r'plugin:[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*')


def is_plugin_record_type(value):
    return _RECORD_TYPE.fullmatch(js_to_string(value)) is not None


def appendPluginRecord(session, record_type, data):
    """Snapshot and publish one ignorable record through the Session capability."""
    publication_entry(session)
    payload = walk_json_value(data, detach=True, undefined_sentinel=UNDEFINED)
    if payload is UNDEFINED:
        raise ValueError('plugin record "%s" carries non-JSON-serializable data' % js_to_string(record_type))
    entry = publication_entry(session)
    event = deep_freeze(dict(type=record_type,seq=len(session._log),time=session._event_time(),data=payload,ignorable=True))
    if not is_plugin_record_type(record_type):
        raise ValueError('plugin record type "%s" must be "plugin:" followed by lowercase slash-separated segments' % js_to_string(record_type))
    session.surface.validateNext(event)
    if entry is not None:
        entry.appending = True
    try:
        args = [session, event]
        callbacks = None if entry is None else _collect_session_callbacks(entry.emit_ctx, [entry.carrier, 'session/event', *args])
        session._log.append(event)
        session._events_snapshot = None
        if entry is not None:
            _invoke_contained_session_observers(entry.emit_ctx, 'session/event', entry.id, args, callbacks)
    finally:
        if entry is not None:
            entry.appending = False
            if entry.detach_requested and not entry.announcing:
                entry.detach()
    return event['seq']


def pluginRecordOf(event):
    """Return record framing with the original payload, or the undefined sentinel."""
    if event.get('ignorable') is not True or not is_plugin_record_type(event['type']):
        return UNDEFINED
    return {key:event[key] for key in ('type','seq','time','data')}
