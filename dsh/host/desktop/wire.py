"""Desktop v3 framed bytes; descriptor selection belongs to the process adapter."""
import json
import math
import struct

from dsh.cordis.json_text import stringify_json

PROTOCOL_VERSION = 3
CHUNK_BYTES = 64 * 1024
CONTROL_BYTES = 1024 * 1024
HEADER = struct.Struct('>IBII')
MAGIC = 0x44534833


class DesktopProtocolError(ValueError):
    name = 'Error'


def stream_id(value):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or int(value) != value or not 1 <= value <= 0xffffffff):
        raise DesktopProtocolError('dsh desktop: invalid pipe stream id %s' % value)
    return int(value)


def encode_frame(kind, identity, payload=b'', direction='response'):
    identity = stream_id(identity)
    limit = CHUNK_BYTES if kind == 2 else CONTROL_BYTES
    if len(payload) > limit:
        raise DesktopProtocolError('dsh desktop: %s pipe frame exceeds the %s-byte limit' % (direction, limit))
    return HEADER.pack(MAGIC, kind, identity, len(payload)) + payload


def encode_start(identity, value, direction='response'):
    return encode_frame(1, identity, stringify_json(value).encode('utf-8'), direction)


def encode_data(identity, value, direction='response'):
    return encode_frame(2, identity, value, direction)


def encode_end(identity, direction='response'):
    return encode_frame(3, identity, direction=direction)


def encode_error(identity, message):
    return encode_frame(4, identity, stringify_json(dict(message=message)).encode('utf-8'))


def headers(value):
    return isinstance(value, list) and all(isinstance(pair, list) and len(pair) == 2
        and all(isinstance(item, str) for item in pair) for pair in value)


class FrameDecoder:
    def __init__(self, direction='request', *, response_credit=False):
        if direction not in ('request', 'response'):
            raise ValueError('Invalid desktop frame direction')
        self.direction, self.buffer = direction, bytearray()
        self.response_credit = response_credit and direction == 'request'

    @property
    def peer(self):
        return 'Electron request' if self.direction == 'request' else 'Host response'

    def push(self, chunk):
        self.buffer.extend(chunk)
        frames = []
        while len(self.buffer) >= HEADER.size:
            magic, kind, identity, size = HEADER.unpack_from(self.buffer)
            if magic != MAGIC:
                raise DesktopProtocolError('dsh desktop: invalid %s frame marker' % self.peer)
            stream_id(identity)
            if self.response_credit and kind == 5 and size:
                raise DesktopProtocolError('dsh desktop: response credit frame carried a payload')
            limit = CHUNK_BYTES if kind == 2 else CONTROL_BYTES
            if size > limit:
                raise DesktopProtocolError('dsh desktop: %s frame exceeds the %s-byte limit' % (self.peer, limit))
            end = HEADER.size + size
            if len(self.buffer) < end:
                break
            payload = bytes(self.buffer[HEADER.size:end])
            del self.buffer[:end]
            frames.append(self.decode(kind, identity, payload))
        return frames

    def decode(self, kind, identity, payload):
        if self.response_credit and kind == 5:
            return dict(type='response-credit', streamId=identity)
        if kind == 2:
            return dict(type='data', streamId=identity, data=payload)
        if kind == 3 or kind == 4 and self.direction == 'request':
            name = 'end' if kind == 3 else 'cancel'
            if payload:
                raise DesktopProtocolError('dsh desktop: %s %s frame carried a payload' % (self.peer, name))
            return dict(type=name, streamId=identity)
        if kind not in ((1, 4) if self.direction == 'response' else (1,)):
            raise DesktopProtocolError('dsh desktop: unknown %s frame type %s' % (self.peer, kind))
        name = 'start' if kind == 1 else 'error'
        try:
            value = json.loads(payload.decode('utf-8', errors='replace'),
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid JSON constant')))
        except ValueError as error:
            # Parser diagnostics are Python-owned; the framing taxonomy is shared.
            raise DesktopProtocolError('dsh desktop: %s %s payload is not JSON: %s' % (self.peer, name, error)) from error
        valid = isinstance(value, dict)
        if name == 'error':
            valid = valid and isinstance(value.get('message'), str)
            fields = ('message',)
        else:
            valid = valid and headers(value.get('headers')) and type(value.get('hasBody')) is bool
            if self.direction == 'request':
                valid = valid and isinstance(value.get('url'), str) and isinstance(value.get('method'), str)
                fields = ('url', 'method', 'headers', 'hasBody')
            else:
                status = value.get('status') if valid else None
                valid = valid and type(status) in (int, float) and 100 <= status <= 599 and int(status) == status
                fields = ('status', 'headers', 'hasBody')
        if not valid:
            raise DesktopProtocolError('dsh desktop: invalid %s %s payload' % (self.peer, name))
        return dict(type=name, streamId=identity, **{key: value[key] for key in fields})

    def finish(self):
        if self.buffer:
            raise DesktopProtocolError('dsh desktop: %s pipe ended inside a frame' % self.peer)
