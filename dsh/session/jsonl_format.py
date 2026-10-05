import math

from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import js_to_string
from dsh.core.session import SESSION_FORMAT_VERSION
from dsh.session.persistence import SessionFormatUnsupportedError
from dsh.session.sqlite_codec import decode_storage_record, pack_chunk_runs
from dsh.session.sqlite_json import parse_json
from dsh.session.sqlite_logical import header_from_stored, logical_numbers
from dsh.session.seq_ranges import decode_seq_ranges, encode_seq_ranges


def units(value):
    encoded = value.encode('utf-16-le', 'surrogatepass')
    return [int.from_bytes(encoded[offset:offset + 2], 'little') for offset in range(0, len(encoded), 2)]


def safe_unit(code):
    return 65 <= code <= 90 or 97 <= code <= 122 or 48 <= code <= 57 or code in (46, 95, 45)


def encode_segment(raw):
    if not raw:
        raise ValueError('cannot encode an empty path segment')
    if raw == '.':
        return '~002E'
    if raw == '..':
        return '~002E~002E'
    return ''.join(chr(code) if safe_unit(code) else '~%04X' % code for code in units(raw))


def project_key(cwd):
    if cwd is None:
        raise TypeError("Cannot read properties of null (reading 'length')")
    if not isinstance(cwd, str):
        length = len(cwd) if isinstance(cwd, list) else cwd.get('length') if isinstance(cwd, dict) else None
        if type(length) in (int, float) and length == 0:
            raise ValueError('cannot encode an empty project path')
        try:
            positive = float(length) > 0 if length is not None else False
        except (TypeError, ValueError, OverflowError):
            positive = False
        if positive:
            raise TypeError('cwd.charCodeAt is not a function')
        return '--root--'
    if not cwd:
        raise ValueError('cannot encode an empty project path')
    readable = []
    separator = False
    for code in units(cwd):
        if code in (47, 92, 58):
            if not separator:
                readable.append('-')
            separator = True
        else:
            readable.append(chr(code) if safe_unit(code) else '~%04X' % code)
            separator = False
    slug = ''.join(readable).lstrip('-') or 'root'
    return '--' + slug[:251] + '--'


def safe_nonnegative(value):
    return (type(value) in (int, float) and math.isfinite(value) and value == int(value)
            and 0 <= value <= 9007199254740991 and not (value == 0 and math.copysign(1, value) < 0))


def is_header(value):
    return (isinstance(value, dict) and value.get('type') == 'session'
            and type(value.get('version')) in (int, float) and isinstance(value.get('id'), str)
            and safe_nonnegative(value.get('createdAt')) and safe_nonnegative(value.get('delegationDepth'))
            and ('origin' not in value or value['origin'] == 'subagent')
            and ('agentPreset' not in value or isinstance(value['agentPreset'], str)))


def from_header(value):
    if 'sandboxMode' in value or 'approvalPolicy' in value:
        raise ValueError('session header uses retired policy baseline fields')
    return header_from_stored(logical_numbers(value))


def parse_header_meta(line):
    try:
        value = parse_json(line)
    except Exception:
        return None
    return from_header(value) if is_header(value) else None


def refuse_version(value):
    if not isinstance(value, dict):
        return
    version = value.get('version')
    if type(version) not in (int, float) or version == SESSION_FORMAT_VERSION:
        return
    identity = value.get('id', 'undefined')
    identity = identity if isinstance(identity, str) else js_to_string(identity)
    rendered = js_to_string(version)
    if version > SESSION_FORMAT_VERSION:
        message = ('session "%s" uses log format v%s, but this harness reads only v%s: the log was written by a newer harness — upgrade the harness to open it'
                   % (identity, rendered, SESSION_FORMAT_VERSION))
    else:
        message = ('session "%s" uses log format v%s, older than the supported v%s, and this build ships no upgrade path for it'
                   % (identity, rendered, SESSION_FORMAT_VERSION))
    raise SessionFormatUnsupportedError(message)


def parse_header_record(record):
    if not record or record[-1:] != b'\n' or record.find(b'\n') != len(record) - 1:
        raise ValueError('empty or header-less session log')
    try:
        value = parse_json(record[:-1].decode('utf-8', 'replace'))
    except Exception:
        raise ValueError('corrupt session log: header line is not valid JSON') from None
    refuse_version(value)
    if not is_header(value):
        raise ValueError('corrupt session log: first line is not a session header')
    return from_header(value)


def header_bytes(meta):
    value = dict(type='session', version=meta.version, id=meta.id, createdAt=meta.created_at)
    metadata = meta.to_dict()
    for name in ('cwd', 'parentSession', 'seedLength', 'origin'):
        if name in metadata:
            value[name] = metadata[name]
    value['delegationDepth'] = meta.delegation_depth or 0
    if 'agentPreset' in metadata:
        value['agentPreset'] = metadata['agentPreset']
    return (stringify_json(value) + '\n').encode('utf-8')


def event_bytes(events, pack_chunks=True):
    records = pack_chunk_runs(events) if pack_chunks else events
    lines = []
    for record in records:
        detached = dict(record)
        if 'sourceEventSeqs' in detached:
            detached['sourceEventSeqs'] = encode_seq_ranges(detached['sourceEventSeqs'])
        lines.append(stringify_json(detached))
    return ('\n'.join(lines) + '\n').encode('utf-8')


class SessionLogScanner:
    def __init__(self, record):
        self.meta = parse_header_record(record)
        self.events = []
        self.fragments = bytearray()
        self.input_bytes = self.committed_bytes = len(record)
        self.event_line = 0
        self.issue = None
        self.finished = False

    def checkpoint(self):
        return dict(inputBytes=self.input_bytes, committedBytes=self.committed_bytes, eventCount=len(self.events))

    def write(self, chunk):
        if self.finished:
            raise ValueError('cannot write to a finished session log scanner')
        start = self.input_bytes
        self.input_bytes += len(chunk)
        line_start = 0
        while True:
            newline = chunk.find(b'\n', line_start)
            if newline < 0:
                self.fragments.extend(chunk[line_start:])
                return
            self.fragments.extend(chunk[line_start:newline])
            line = bytes(self.fragments)
            self.fragments.clear()
            self._consume(line, start + newline + 1)
            line_start = newline + 1

    def _consume(self, line, end):
        self.event_line += 1
        try:
            value = logical_numbers(parse_json(line.decode('utf-8', 'replace')))
            if isinstance(value, dict) and 'sourceEventSeqs' in value:
                value['sourceEventSeqs'] = decode_seq_ranges(value['sourceEventSeqs'], value['seq'])
            decoded = decode_storage_record(value)
        except Exception:
            if self.issue is None:
                self.issue = ValueError('corrupt session log: unparsable committed event at line %s' % self.event_line)
            return
        if self.issue is not None:
            if any(event['type'] == 'turn/end' for event in decoded):
                raise self.issue
            return
        row_start = len(self.events)
        for event in decoded:
            if event['seq'] != len(self.events):
                expected = len(self.events)
                del self.events[row_start:]
                self.issue = ValueError('corrupt session log: seq gap in committed region at line %s (expected %s, got %s)'
                    % (self.event_line, expected, js_to_string(event['seq'])))
                if any(candidate['type'] == 'turn/end' for candidate in decoded):
                    raise self.issue
                return
            self.events.append(event)
        self.committed_bytes = end

    def finish(self):
        self.finished = True
        return dict(meta=self.meta, events=self.events, committedBytes=self.committed_bytes)


def scan_log(buffer):
    boundary = buffer.find(b'\n')
    if boundary < 0:
        raise ValueError('empty or header-less session log')
    scanner = SessionLogScanner(buffer[:boundary + 1])
    scanner.write(buffer[boundary + 1:])
    return scanner.finish()
