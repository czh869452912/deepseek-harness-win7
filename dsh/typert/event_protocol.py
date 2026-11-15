"""Validated forwarded-event results, independent of transport ownership."""
from dsh.typert.remote_events import lossless


def parse_result(value):
    invalid = 'api gateway: invalid Remote event result'
    if type(value) is not dict or set(value) != {'clientId', 'eventId', 'outcome'} or any(not isinstance(value[key], str) or not value[key] for key in ('clientId', 'eventId')) or type(value['outcome']) is not dict:
        raise ValueError(invalid)
    outcome = value['outcome']
    kind = outcome.get('kind')
    if kind == 'next' and set(outcome) == {'kind'}:
        projected = dict(kind='next')
    elif kind == 'result' and set(outcome) in ({'kind'}, {'kind', 'value'}):
        if 'value' in outcome:
            try:
                lossless(outcome['value'])
            except Exception:
                raise ValueError(invalid)
        projected = dict(outcome)
    elif kind == 'rejected' and set(outcome) == {'kind', 'error'}:
        error = outcome['error']
        if type(error) is not dict or not {'name', 'message'}.issubset(error) or set(error) - {'name', 'message', 'code', 'details'} or not isinstance(error['name'], str) or not error['name'] or not isinstance(error['message'], str) or 'code' in error and not isinstance(error['code'], str):
            raise ValueError('api gateway: invalid Remote event rejection')
        if 'details' in error:
            try:
                lossless(error['details'])
            except Exception:
                raise ValueError('api gateway: invalid Remote event rejection')
        projected = dict(kind='rejected', error=dict(error))
    else:
        raise ValueError(invalid)
    return dict(clientId=value['clientId'], eventId=value['eventId'], outcome=projected)
