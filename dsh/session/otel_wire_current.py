"""OTLP JSON payloads for one caller-owned resource and instrumentation scope."""
import base64
import math
import time

from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _UNDEFINED, _js_own_enumerable_keys

_TIME_ORIGIN = time.time()*1000


def _valid_attribute(value, seen=None):
    if value is None or value is _UNDEFINED or type(value) in (str, int, float, bool, bytes): return True
    if not isinstance(value, (dict, list)): return False
    if seen is None: seen = set()
    if id(value) in seen: return False
    seen.add(id(value))
    values = value.values() if isinstance(value, dict) else value
    return all(_valid_attribute(item, seen) for item in values)


def any_value(value):
    if isinstance(value, str): return dict(stringValue=value)
    if isinstance(value, bool): return dict(boolValue=value)
    if type(value) in (int, float):
        return {'intValue' if math.isfinite(value) and value == int(value) else 'doubleValue': value}
    if isinstance(value, bytes): return dict(bytesValue=base64.b64encode(value).decode('ascii'))
    if isinstance(value, list): return dict(arrayValue=dict(values=[any_value(item) for item in value]))
    if isinstance(value, dict): return dict(kvlistValue=dict(values=attributes(value)))
    return {}


def attributes(value):
    return [dict(key=key, value=any_value(value[key])) for key in _js_own_enumerable_keys(value)]


def _timestamp(value, now, time_origin):
    if value is None or value is _UNDEFINED: value = now
    if isinstance(value, list) and len(value) == 2 and all(type(item) in (int, float) for item in value):
        return str(int(value[0])*1000000000+int(value[1]))
    if type(value) not in (int, float): raise TypeError('Invalid input type')
    if value < time_origin/2: value += time_origin
    seconds = math.trunc(value/1000)
    nanos = math.floor(math.fmod(value, 1000)*1000000+0.5)
    return str(seconds*1000000000+nanos)


def log_record(record, session=False, now=None, time_origin=None):
    if now is None: now = time.time()*1000
    if time_origin is None: time_origin = _TIME_ORIGIN
    admitted = {}; dropped = 0
    source = record.get('attributes') or {}
    for key in _js_own_enumerable_keys(source):
        value = source[key]
        if not key or not _valid_attribute(value): continue
        if not session and len(admitted) >= 128:
            dropped += 1; continue
        admitted[key] = value
    result = dict(timeUnixNano=_timestamp(record.get('timestamp'), now, time_origin),
        observedTimeUnixNano=_timestamp(record.get('observedTimestamp'), now, time_origin))
    for key in ('severityNumber', 'severityText'):
        if key in record and record[key] is not _UNDEFINED: result[key] = record[key]
    result['body'] = any_value(record.get('body'))
    if 'eventName' in record: result['eventName'] = record['eventName']
    result.update(attributes=attributes(admitted), droppedAttributesCount=dropped)
    return result


def serialize_records(records, scope, resource_attributes, session=False, now=None, time_origin=None):
    if not records: return b'{"resourceLogs":[]}'
    instrument = dict(name=scope['name'])
    if scope.get('version') is not None: instrument['version'] = scope['version']
    resource_attributes = {key: value for key, value in resource_attributes.items()
                           if value is not None and value is not _UNDEFINED}
    payload = dict(resourceLogs=[dict(resource=dict(attributes=attributes(resource_attributes), droppedAttributesCount=0),
        scopeLogs=[dict(scope=instrument, logRecords=[log_record(record, session, now, time_origin) for record in records])])])
    return stringify_json(payload).encode('utf-8')
