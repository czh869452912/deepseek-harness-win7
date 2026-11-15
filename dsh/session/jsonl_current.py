"""Canonical v3 JSONL framing and incremental committed-prefix recovery.

Historical generations are read by the migration catalog, never by this
current-generation scanner. Byte offsets refer to original UTF-8 input.
"""
import os

from dsh.core.session.json import UNDEFINED
from dsh.core.session.types import SessionLogOffset
from dsh.core.session.current import safe
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _js_strict_equal
from dsh.session.format import parseSessionFormatLogFilename, sessionFormatLogFilename, SessionFormatUnsupportedMigrationError
from dsh.session.format_catalog import sessionFormatCatalog
from dsh.session.format_v2_to_v3 import assertV3RowAdmission
from dsh.session.format_v2_to_v3.payload import display
from dsh.session.format_v1_to_v2.codec import HEADER_REQUIRED, HEADER_OPTIONAL
from dsh.session.persistence import SessionFormatUnsupportedError
from dsh.session.sqlite_json import parse_json
from dsh.session.jsonl_format import encode_segment, project_key


def logSuffix(compression):
    return '.jsonl.zstd' if compression == 'zstd' else '.jsonl'


def generationLogFilename(version, compression):
    return sessionFormatLogFilename(version) + ('.zstd' if compression == 'zstd' else '')


def parseGenerationLogFilename(filename, compression):
    if compression == 'zstd':
        if not filename.endswith('.zstd'):
            return None
        filename = filename[:-5]
    return parseSessionFormatLogFilename(filename)


def projectDir(root, cwd=UNDEFINED):
    return os.path.join(root, '_no-cwd' if cwd is UNDEFINED else project_key(cwd))


def sessionDir(root, cwd, identity):
    return os.path.join(projectDir(root, cwd), encode_segment(identity))


def generationLogPath(root, cwd, identity, version, compression):
    return os.path.join(sessionDir(root, cwd, identity), generationLogFilename(version, compression))


def logPath(root, cwd, identity, compression, format_version=3):
    return generationLogPath(root, cwd, identity, format_version, compression)


def assertNoRetiredHeaderFields(value):
    if isinstance(value, dict) and any(key in value for key in ('sandboxMode', 'approvalPolicy')):
        raise ValueError('session header uses retired policy baseline fields')


def toHeaderLine(header, inheritedEventCount=UNDEFINED, format_version=3):
    if hasattr(header, 'to_dict'):
        header = header.to_dict()
    if header.get('isSeeded') and inheritedEventCount is UNDEFINED:
        raise ValueError('seeded session header requires an inherited event count')
    cut = SessionLogOffset(0 if inheritedEventCount is UNDEFINED or inheritedEventCount is None else inheritedEventCount)
    if not header.get('isSeeded') and cut != 0:
        raise ValueError('unseeded session header inherited event count must be 0')
    depth = header.get('delegationDepth', UNDEFINED)
    catalog = sessionFormatCatalog
    if format_version == 4:
        from dsh.session.format_catalog import candidateSessionFormatCatalog
        catalog = candidateSessionFormatCatalog
    return catalog.encodeCurrentHeader(dict(header, delegationDepth=0 if depth is UNDEFINED or depth is None else depth), cut)


def eventLine(event, format_version=3):
    catalog = sessionFormatCatalog
    if format_version == 4:
        from dsh.session.format_catalog import candidateSessionFormatCatalog
        catalog = candidateSessionFormatCatalog
    return stringify_json(catalog.encodeCurrentEvent(event))


def eventLines(events, format_version=3):
    return '\n'.join(eventLine(event, format_version) for event in events)


def header_bytes(header, inheritedEventCount=UNDEFINED, format_version=3):
    return (stringify_json(toHeaderLine(header, inheritedEventCount, format_version))+'\n').encode('utf-8')


def is_header(value):
    return (isinstance(value, dict) and all(key in value for key in HEADER_REQUIRED)
        and all(key in HEADER_REQUIRED or key in HEADER_OPTIONAL for key in value)
        and value['type'] == 'session' and type(value['version']) in (int, float)
        and isinstance(value['id'], str) and safe(value['createdAt'], True, True)
        and safe(value['delegationDepth'], True, True)
        and (value.get('cwd', UNDEFINED) is UNDEFINED or isinstance(value['cwd'], str) and os.path.isabs(value['cwd']))
        and (value.get('parentSession', UNDEFINED) is UNDEFINED or isinstance(value['parentSession'], str))
        and type(value['isSeeded']) is bool
        and (value.get('origin', UNDEFINED) is UNDEFINED or value['origin'] == 'subagent')
        and (value.get('agentPreset', UNDEFINED) is UNDEFINED or isinstance(value['agentPreset'], str)))


def parseHeaderRecord(record, format_version=3):
    if not record or record[-1:] != b'\n' or record.find(b'\n') != len(record)-1:
        raise ValueError('empty or header-less session log')
    try:
        value = parse_json(record[:-1].decode('utf-8', 'replace'))
    except Exception:
        raise ValueError('corrupt session log: header line is not valid JSON') from None
    if not isinstance(value, dict):
        raise ValueError('corrupt session log: first line is not a JSON object')
    version = value.get('version', UNDEFINED)
    if type(version) in (int, float) and not _js_strict_equal(version, format_version):
        identity = display(value.get('id', UNDEFINED))
        message = (('session "%s" uses log format v%s, but this harness reads only v%s: the log was written by a newer harness — upgrade the harness to open it' if version > format_version else 'session "%s" uses log format v%s, older than the supported v%s, and this build ships no upgrade path for it') % (identity, display(version), format_version))
        raise SessionFormatUnsupportedError(message)
    assertNoRetiredHeaderFields(value)
    if not is_header(value):
        raise ValueError('corrupt session log: first line is not a session header')
    try:
        catalog = sessionFormatCatalog
        if format_version == 4:
            from dsh.session.format_catalog import candidateSessionFormatCatalog
            catalog = candidateSessionFormatCatalog
        restore = catalog.createRestore(value, dict(recovery='strict', validation='transformed'))
    except Exception:
        raise ValueError('corrupt session log: first line is not a session header') from None
    return dict(meta={key:item for key,item in value.items() if key != 'type'}, restore=restore)


class SessionLogScanner:
    def __init__(self, headerRecord, recovery='recoverable', format_version=3):
        parsed = parseHeaderRecord(headerRecord, format_version)
        self.format_version = format_version
        self.meta, self.restore = parsed['meta'], parsed['restore']
        self.recovery, self.event_count, self.event_line = recovery, 0, 0
        self.fragments = bytearray()
        self.input_bytes = self.committed_bytes = len(headerRecord)
        self.issue, self.finished = None, False

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
            self.consume(line, start+newline+1)
            line_start = newline+1

    def checkpoint(self):
        return dict(inputBytes=self.input_bytes, committedBytes=self.committed_bytes, eventCount=self.event_count)

    def finish(self):
        self.finished = True
        artifact = self.restore.finish()
        if self.format_version == 4:
            from dsh.session.format_v3_to_v4 import assertReleasedV4Relationships
            from dsh.core.session.current_vocabulary import V4_SESSION_EVENT_TYPES
            assertReleasedV4Relationships(artifact, V4_SESSION_EVENT_TYPES)
        return dict(meta=self.meta, inheritedEventCount=SessionLogOffset(artifact['inheritedEventCount']),
            events=artifact['events'], committedBytes=self.committed_bytes)

    def consume(self, line, end):
        self.event_line += 1
        try:
            decoded = parse_json(line.decode('utf-8', 'replace'))
        except Exception:
            issue = ValueError('corrupt session log: unparsable committed event at line %s' % self.event_line)
            if self.recovery == 'strict':
                raise issue from None
            self.issue = self.issue or issue
            return
        try:
            if self.format_version == 4:
                from dsh.session.format_v3_to_v4 import assertV4RowAdmission
                from dsh.core.session.current_vocabulary import V4_SESSION_EVENT_TYPES
                assertV4RowAdmission(decoded, V4_SESSION_EVENT_TYPES)
            else:
                assertV3RowAdmission(decoded)
        except SessionFormatUnsupportedMigrationError as error:
            raise SessionFormatUnsupportedError(str(error)) from None
        if self.issue is not None:
            if isinstance(decoded, dict) and decoded.get('type') == 'turn/end':
                raise self.issue
            return
        try:
            self.restore.decodeRow(decoded)
        except Exception as error:
            issue = ValueError('corrupt session log: invalid committed event at line %s: %s' % (self.event_line, error))
            issue.cause = error
            if self.recovery == 'strict':
                raise issue from error
            self.issue = issue
            if isinstance(decoded, dict) and decoded.get('type') == 'turn/end':
                raise issue from error
            return
        self.event_count += 1
        self.committed_bytes = end


def scanLog(buffer, format_version=3):
    boundary = buffer.find(b'\n')
    if boundary < 0:
        raise ValueError('empty or header-less session log')
    scanner = SessionLogScanner(buffer[:boundary+1], format_version=format_version)
    scanner.write(buffer[boundary+1:])
    return scanner.finish()
