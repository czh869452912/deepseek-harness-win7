"""Exact-key JSON frames for the duplex Remote stream carrier."""
import json
import math
from dsh.typert.remote_events import lossless


def _integer(text):
    # JSON.parse stores every JSON number in an IEEE-754 double. Preserve -0
    # for the lossless item check and round large integers before Host use.
    value = float(text)
    if value == 0 and text.startswith('-'):
        return -0.0
    return int(value) if math.isfinite(value) else value


def _parse(text, direction):
    try:
        value = json.loads(text, parse_int=_integer, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise ValueError('api gateway: Remote stream message is not JSON')
    if type(value) is not dict:
        raise ValueError('api gateway: Remote stream message must be an object')
    valid = isinstance(value.get('streamId'), str) and bool(value['streamId'])
    kind, keys = value.get('type'), set(value)
    admitted = False
    if direction == 'client':
        if kind in ('cancel', 'end'):
            admitted = keys == {'type', 'streamId'}
        elif kind == 'open':
            admitted = keys == {'type', 'streamId', 'endpoint', 'payload'} and isinstance(value['endpoint'], str) and bool(value['endpoint'])
        elif kind == 'item' and keys in ({'type', 'streamId'}, {'type', 'streamId', 'value'}):
            try:
                if 'value' in value:
                    lossless(value['value'])
                admitted = True
            except ValueError:
                pass
    else:
        if kind == 'end':
            admitted = keys == {'type', 'streamId'}
        elif kind == 'item':
            admitted = keys in ({'type', 'streamId'}, {'type', 'streamId', 'value'})
        elif kind == 'error' and keys == {'type', 'streamId', 'error'}:
            error = value['error']
            admitted = type(error) is dict and set(error) == {'code', 'message', 'details'} and isinstance(error['code'], str) and isinstance(error['message'], str) and type(error['details']) is dict
    if not valid or not admitted:
        raise ValueError('api gateway: invalid Remote stream {} message'.format(direction))
    return value


def parse_client_message(text):
    return _parse(text, 'client')


def parse_server_message(text):
    return _parse(text, 'server')
