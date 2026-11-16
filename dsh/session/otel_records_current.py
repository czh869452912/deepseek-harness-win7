"""Pinned OTel channel admission and emitted record envelopes."""
import math

from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _UNDEFINED

SESSION_LOG_MAX_REQUEST_BYTES = 4000000


def _integer(value, maximum):
    return (type(value) in (int, float) and 1 <= value <= maximum
            and math.isfinite(value) and value == int(value))


def resolve_session_log_limits(options):
    limit = options.get('maxRequestBytes')
    if limit is None: limit = SESSION_LOG_MAX_REQUEST_BYTES
    if not _integer(limit, SESSION_LOG_MAX_REQUEST_BYTES):
        raise ValueError('session log maxRequestBytes must be an integer between 1 and 4000000')
    processor = options.get('processor') or {}
    for key in ('maxQueueSize', 'maxExportBatchSize', 'scheduledDelayMillis', 'exportTimeoutMillis'):
        if key in processor and not _integer(processor[key], 2147483647):
            raise ValueError('session log processor.'+key+' must be a positive integer no greater than 2147483647')
    queue = processor.get('maxQueueSize', 2048)
    batch = processor.get('maxExportBatchSize', 512)
    if batch > queue:
        raise ValueError('session log maxExportBatchSize must not exceed maxQueueSize')
    return int(limit)


_SEVERITIES = {0: 'UNSPECIFIED'}
for _base, _name in ((1, 'TRACE'), (5, 'DEBUG'), (9, 'INFO'), (13, 'WARN'), (17, 'ERROR'), (21, 'FATAL')):
    for _offset in range(4):
        _SEVERITIES[_base+_offset] = _name+(str(_offset+1) if _offset else '')


def _severity(record):
    value = record.get('severityNumber')
    if value is None: value = 9
    if isinstance(value, str):
        reverse = {name: number for number, name in _SEVERITIES.items()}
        if value in reverse: return value, reverse[value]
    key = value
    if isinstance(key, str):
        try:
            number = int(key)
            key = number if str(number) == key else _UNDEFINED
        except ValueError: key = _UNDEFINED
    if type(key) not in (int, float): key = _UNDEFINED
    return value, _SEVERITIES.get(key, _UNDEFINED)


def event_log_record(record, observed_timestamp):
    result = dict(record)
    number, text = _severity(record)
    result.update(observedTimestamp=observed_timestamp, severityNumber=number, severityText=text)
    return result


def session_log_record(record):
    number, text = _severity(record)
    event = record['event']
    attributes = dict(record.get('attributes') or {})
    attributes.update(sessionId=record['sessionId'], content=stringify_json(event))
    return dict(eventName='session-log', body='session-log', timestamp=event['time'],
        observedTimestamp=event['time'], severityNumber=number, severityText=text, attributes=attributes)
