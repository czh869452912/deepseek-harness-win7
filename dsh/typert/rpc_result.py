"""Materialize one RPC result once and extract its byte attachments."""
import datetime
import math
from dsh.core.session.json import UNDEFINED
from dsh.typert.artifact import UNDEFINED as CODEC_UNDEFINED
from dsh.cordis.utils import _js_own_enumerable_keys


def absent(value):
    return value is UNDEFINED or value is CODEC_UNDEFINED


def _bytes(value):
    return isinstance(value, (bytes, bytearray, memoryview))


def encode_runtime_result(value, write_bytes):
    path, ancestors = [], set()
    def extract(value, key):
        if not _bytes(value):
            to_json = value.get('toJSON') if isinstance(value, dict) else getattr(value, 'toJSON', None)
            if callable(to_json):
                value = to_json(key)
            elif isinstance(value, datetime.datetime):
                instant = value if value.tzinfo is not None else value.replace(tzinfo=datetime.timezone.utc)
                value = instant.astimezone(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        if _bytes(value):
            return write_bytes(value, list(path))
        if value is None or type(value) in (str, bool, int, float) or absent(value) or callable(value):
            return value
        identity = id(value)
        if identity in ancestors:
            raise TypeError('gateway: circular RPC result')
        ancestors.add(identity)
        try:
            if isinstance(value, (list, tuple)):
                return [child(item, index) for index, item in enumerate(value)]
            result = {}
            fields = value if isinstance(value, dict) else vars(value) if hasattr(value, '__dict__') else {}
            for name in _js_own_enumerable_keys(fields):
                item = fields[name]
                if name == 'toJSON' and callable(item):
                    continue
                result[name] = child(item, name)
            return result
        finally:
            ancestors.remove(identity)
    def child(value, key):
        path.append(key)
        try:
            return extract(value, str(key))
        finally:
            path.pop()
    return extract(value, 'value')


def encode_rpc_result(value, codec):
    attachments = []
    def write_bytes(data, path):
        attachments.append(dict(path=list(path), bytes=data))
        return None
    if codec['mode'] == 'strict':
        encode = codec.get('encode')
        encoded = encode(value, write_bytes) if encode is not None else value
        if encoded is None or absent(encoded):
            encoded = value
    else:
        encoded = encode_runtime_result(value, write_bytes)
    result = dict(ok=True, value=encoded)
    if attachments:
        result['attachments'] = attachments
    return result


def json_projection(value):
    """JSON.stringify rules for the already-materialized response metadata."""
    if absent(value) or callable(value):
        return UNDEFINED
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if _bytes(value):
        return {str(index): item for index, item in enumerate(bytes(value))}
    if isinstance(value, (list, tuple)):
        return [None if absent(item) else item for item in (json_projection(item) for item in value)]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            item = json_projection(item)
            if not absent(item):
                result[key] = item
        return result
    return value
