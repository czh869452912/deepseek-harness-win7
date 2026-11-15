"""Current (v3) persistence seam's backend-independent admission contract."""
from dsh.core.session.current import adoptSessionEvent, safe
from dsh.core.session.current_vocabulary import KNOWN_SESSION_EVENT_TYPES
from dsh.core.session.json import UNDEFINED, walk_json_value
from dsh.session.format_v2_to_v3.payload import display
from dsh.session.persistence import SessionFormatUnsupportedError, SessionPersistenceCorruptionError


def field(value, name, default=UNDEFINED):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def sessionFormatVersionRefusal(session_id, version):
    start = 'session "%s" uses log format v%s' % (session_id, display(version))
    if isinstance(version, (int, float)) and version > 3:
        return start + ', but this harness reads only v3: the log was written by a newer harness — upgrade the harness to open it'
    return start + ', older than the supported v3, and this build ships no upgrade path for it'


def unsupported(reason, location):
    return SessionFormatUnsupportedError(reason if location is None else reason + ' (raw log: %s)' % field(location, 'path'), location)


def assertStoredId(session_id, meta):
    if field(meta, 'id') != session_id:
        raise ValueError('stored session identity mismatch: requested "%s", header contains "%s"' % (display(session_id), display(field(meta, 'id'))))


def assertVersion(meta, location=None):
    version = field(meta, 'version')
    if isinstance(version, bool) or version != 3:
        raise unsupported(sessionFormatVersionRefusal(field(meta, 'id'), version), location)


def validateStoredEvents(meta, events, location=None, format_version=3):
    known = KNOWN_SESSION_EVENT_TYPES
    if format_version == 4:
        from dsh.core.session.current_vocabulary import V4_SESSION_EVENT_TYPES
        known = V4_SESSION_EVENT_TYPES
    session_id = field(meta, 'id')
    for event in events:
        kind, seq = field(event, 'type'), field(event, 'seq')
        if kind not in known and field(event, 'ignorable') is not True:
            raise unsupported('session "%s" contains event type "%s" (seq %s) unknown to this harness and not marked ignorable; refusing to interpret the log — it was likely written by a newer harness' % (session_id, display(kind), display(seq)), location)
        if kind == 'request/header' and field(field(event, 'data'), 'reason') == 'fallback':
            raise unsupported('session "%s" contains a request/header event (seq %s) with the unsupported legacy reason "fallback"; refusing to interpret the log — it was written by a retired pre-release harness' % (session_id, display(seq)), location)
    try:
        for index, event in enumerate(events):
            events[index] = adoptSessionEvent(event, format_version)
    except SessionFormatUnsupportedError:
        raise
    except Exception as error:
        name = getattr(error, 'name', 'TypeError' if isinstance(error, TypeError) else 'Error')
        raise SessionPersistenceCorruptionError('stored session "%s" failed validation: %s: %s' % (session_id, name, error), {'cause': error}) from error
    return events


def materializeCreateHeader(header):
    if hasattr(header, 'to_dict'):
        header = header.to_dict()
    snapshot = walk_json_value(header, detach=True, undefined_sentinel=UNDEFINED)
    if snapshot is UNDEFINED:
        raise TypeError('session metadata must be losslessly JSON-serializable')
    if not safe(field(snapshot, 'createdAt'), True):
        raise TypeError('session metadata createdAt must be a non-negative safe integer')
    return snapshot


def materializeAppendBatch(events):
    batch = walk_json_value(events, detach=True, undefined_sentinel=UNDEFINED)
    if batch is UNDEFINED:
        raise TypeError('session event batch is not losslessly JSON-serializable because it contains non-JSON-serializable data')
    return batch


def assertContiguous(session_id, events, cursor):
    for index, event in enumerate(events):
        seq = field(event, 'seq')
        if isinstance(seq, bool) or seq != cursor + index:
            raise ValueError('append seq mismatch for "%s": expected %s at index %s, got %s' % (session_id, display(cursor + index), index, display(seq)))
