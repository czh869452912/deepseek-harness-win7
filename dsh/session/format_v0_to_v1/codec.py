"""Frozen rc.3 released v0/v1 framing, packed runs, and row-atomic recovery.

Physical decoding deliberately retains opaque event payloads. It is not logical
artifact validation and must not be used alone to publish a migrated Session.
"""
import json
import os

from dsh.core.session.json import UNDEFINED, FrozenDict
from dsh.cordis.utils import js_to_string
from dsh.session.format import (SessionFormatError, sessionFormatCount, sessionFormatSafeInteger,
    snapshotSessionFormatJson)

HEADER_REQUIRED = ('type', 'version', 'id', 'createdAt', 'delegationDepth')
HEADER_OPTIONAL = ('cwd', 'parentSession', 'seedLength', 'origin', 'agentPreset')
LOGICAL_REQUIRED = ('version', 'id', 'createdAt', 'isSeeded', 'delegationDepth')
LOGICAL_OPTIONAL = ('cwd', 'parentSession', 'origin', 'agentPreset')
PACKED_TAGS = frozenset(('text-chunks', 'reasoning-chunks', 'tool-call-chunks'))


def record(value, label):
    if not isinstance(value, dict):
        raise SessionFormatError(label + ' must be a JSON object')
    return value


def exact_keys(value, required, optional, label):
    allowed = set(required) | set(optional)
    unexpected = next((key for key in value if key not in allowed), UNDEFINED)
    if unexpected is not UNDEFINED:
        raise SessionFormatError(label + ' has unexpected member ' + json.dumps(unexpected, ensure_ascii=False))
    missing = next((key for key in required if key not in value), UNDEFINED)
    if missing is not UNDEFINED:
        raise SessionFormatError(label + ' lacks required member ' + json.dumps(missing, ensure_ascii=False))


def assertReleasedSessionFormatHeader(header, version):
    label = 'format v%s header' % version
    value = record(header, label)
    exact_keys(value, LOGICAL_REQUIRED, LOGICAL_OPTIONAL, label)
    if type(value['version']) not in (int, float) or value['version'] != version:
        raise SessionFormatError('expected format v%s header' % version)
    if not isinstance(value['id'], str):
        raise SessionFormatError(label + ' id must be a string')
    sessionFormatCount(value['createdAt'], label + ' createdAt')
    if type(value['isSeeded']) is not bool:
        raise SessionFormatError(label + ' isSeeded must be a boolean')
    sessionFormatCount(value['delegationDepth'], label + ' delegationDepth')
    for key in ('cwd', 'parentSession', 'agentPreset'):
        if value.get(key, UNDEFINED) is not UNDEFINED and not isinstance(value[key], str):
            raise SessionFormatError(label + ' %s must be a string' % key)
    if isinstance(value.get('cwd'), str) and not os.path.isabs(value['cwd']):
        raise SessionFormatError(label + ' cwd must be absolute')
    if value.get('origin', UNDEFINED) is not UNDEFINED and value['origin'] != 'subagent':
        raise SessionFormatError(label + ' origin must be "subagent"')


def decodePhysicalHeader(value, version):
    label = 'released v%s physical header' % version
    source = record(snapshotSessionFormatJson(value, label), label)
    exact_keys(source, HEADER_REQUIRED, HEADER_OPTIONAL, label)
    if source['type'] != 'session' or type(source['version']) not in (int, float) or source['version'] != version:
        raise SessionFormatError('expected released v%s physical Session header' % version)
    label = 'released v%s header' % version
    if not isinstance(source['id'], str):
        raise SessionFormatError(label + ' id must be a string')
    created = sessionFormatCount(source['createdAt'], label + ' createdAt')
    depth = sessionFormatCount(source['delegationDepth'], label + ' delegationDepth')
    cut = 0 if 'seedLength' not in source else sessionFormatCount(source['seedLength'], label + ' seedLength')
    for key in ('cwd', 'parentSession', 'agentPreset'):
        if key in source and not isinstance(source[key], str):
            raise SessionFormatError(label + ' %s must be a string' % key)
    if 'origin' in source and source['origin'] != 'subagent':
        raise SessionFormatError(label + ' origin must be "subagent"')
    header = dict(version=version, id=source['id'], createdAt=created)
    header.update({key: source[key] for key in ('cwd', 'parentSession') if key in source})
    header['isSeeded'] = 'seedLength' in source
    if 'origin' in source:
        header['origin'] = source['origin']
    header['delegationDepth'] = depth
    if 'agentPreset' in source:
        header['agentPreset'] = source['agentPreset']
    assertReleasedSessionFormatHeader(header, version)
    return header, cut


def decodeSeqRanges(value, maxEntries):
    if not isinstance(value, list):
        raise SessionFormatError('sourceEventSeqs must be an array')
    output, has_range = [], False
    for entry in value:
        if type(entry) in (int, float):
            if len(output) >= maxEntries:
                raise SessionFormatError('sourceEventSeqs exceeds its event seq')
            output.append(sessionFormatCount(entry, 'sourceEventSeqs member'))
            continue
        if not isinstance(entry, list) or len(entry) != 2:
            raise SessionFormatError('sourceEventSeqs range must be a [start, end] pair')
        first = sessionFormatCount(entry[0], 'sourceEventSeqs range start')
        last = sessionFormatCount(entry[1], 'sourceEventSeqs range end')
        if last < first or last - first + 1 > maxEntries - len(output):
            raise SessionFormatError('sourceEventSeqs range exceeds its event seq')
        output.extend(range(int(first), int(last) + 1))
        has_range = True
    if has_range and any(output[index] <= output[index-1] for index in range(1, len(output))):
        raise SessionFormatError('sourceEventSeqs ranges must be strictly increasing')
    return output


def decodeEvent(value, rowIndex):
    if value.get('sourceEventSeqs', UNDEFINED) is not UNDEFINED:
        seq = sessionFormatCount(value.get('seq', UNDEFINED), 'released Session row %s seq' % rowIndex)
        return dict(value, sourceEventSeqs=decodeSeqRanges(value['sourceEventSeqs'], seq))
    return value


def isReleasedAssistantChunkRun(run):
    return isinstance(run, dict) and run.get('runType') == 'released-assistant-chunks'


def decodePackedRun(row, tag, rowIndex):
    label = 'released %s row %s' % (tag, rowIndex)
    exact_keys(row, ('type', 'seq0', 'time0', 'data'), (), label)
    first = sessionFormatCount(row['seq0'], label + ' seq0')
    time = sessionFormatSafeInteger(row['time0'], label + ' time0')
    data = record(row['data'], label + ' data')
    tool = tag == 'tool-call-chunks'
    required = ('turn', 'step', 'index', 'id', 'dt', 'args') if tool else ('turn', 'step', 'index', 'dt', 'texts')
    exact_keys(data, required, ('name',) if tool else (), label + ' data')
    payload = data['args' if tool else 'texts']
    if not isinstance(payload, list) or not payload or any(not isinstance(item, str) for item in payload):
        raise SessionFormatError(label + ' payload must be a non-empty string array')
    gaps = data['dt']
    if not isinstance(gaps, list) or len(gaps) != len(payload) - 1:
        raise SessionFormatError(label + ' dt length must match its payload')
    last_time = time
    for gap in gaps:
        delta = sessionFormatSafeInteger(gap, label + ' dt member')
        last_time = sessionFormatSafeInteger(last_time + delta, label + ' member time')
    turn = sessionFormatCount(data['turn'], label + ' turn')
    step = sessionFormatCount(data['step'], label + ' step')
    index = sessionFormatCount(data['index'], label + ' index')
    if tool and (not isinstance(data['id'], str) or not data['id']
            or 'name' in data and not isinstance(data['name'], str)):
        raise SessionFormatError(label + ' id and optional name must be strings')
    last = sessionFormatCount(first + len(payload) - 1, label + ' final seq')
    stream = dict(type=tag, time0=time, index=index, dt=gaps)
    stream.update({key: data[key] for key in (('id', 'name', 'args') if tool else ('texts',)) if key in data})
    run = dict(runType='released-assistant-chunks', firstSeq=first, eventCount=len(payload), turn=turn,
        step=step, lastSeq=last, lastTime=last_time, stream=stream)
    run['expand'] = lambda: expandAssistantChunkRun(run)
    return run


def expandAssistantChunkRun(run):
    stream = run['stream']
    tool = stream['type'] == 'tool-call-chunks'
    time = stream['time0']
    for index, value in enumerate(stream['args' if tool else 'texts']):
        if index:
            time += stream['dt'][index-1]
        if tool:
            chunk = dict(type='tool-call-delta', index=stream['index'], id=stream['id'], argumentsDelta=value)
            if 'name' in stream:
                chunk['name'] = stream['name']
        else:
            chunk = dict(type='text-delta' if stream['type'] == 'text-chunks' else 'reasoning-delta',
                index=stream['index'], text=value)
        yield dict(type='assistant/chunk', seq=run['firstSeq'] + index, time=time,
            data=dict(turn=run['turn'], step=run['step'], chunk=chunk))


class ReleasedDecoder:
    def __init__(self, value, version, recovery):
        self.header, self.headerInheritedEventCount = decodePhysicalHeader(value, version)
        self._recoverable = recovery == 'recoverable'
        self._rowIndex, self._eventCount, self._issue = 0, 0, None

    def decodeRow(self, value, context):
        index = self._rowIndex
        self._rowIndex += 1
        packed = False
        try:
            row = record(value, 'released Session row %s' % index)
            tag = row.get('type', UNDEFINED)
            packed = isinstance(tag, str) and tag in PACKED_TAGS
            decoded = decodePackedRun(row, tag, index) if packed else decodeEvent(row, index)
        except Exception as error:
            current = error
            if not isinstance(current, SessionFormatError):
                current = SessionFormatError('released Session row %s is malformed' % index)
                current.cause = error
            if not self._recoverable:
                raise current
            self._issue = self._issue or current
            return
        if self._issue is not None:
            if not packed and decoded.get('type') == 'turn/end':
                raise self._issue
            return
        seq = decoded.get('firstSeq' if packed else 'seq', UNDEFINED)
        if type(seq) not in (int, float) or seq != self._eventCount:
            gap = SessionFormatError('released Session row %s has seq gap (expected %s, got %s)' % (
                index, self._eventCount, js_to_string(seq)))
            if not self._recoverable:
                raise gap
            self._issue = gap
            if not packed and decoded.get('type') == 'turn/end':
                raise gap
            return
        self._eventCount += decoded['eventCount'] if packed else 1
        if packed:
            context.emitRun(decoded)
        else:
            context.emitEvent(decoded)

    def finish(self, context):
        if self.headerInheritedEventCount > self._eventCount:
            raise SessionFormatError('Session inheritedEventCount exceeds its event count')
        return self.headerInheritedEventCount


def createReleasedCodec(version):
    return FrozenDict(version=version, decodeHeader=lambda value: decodePhysicalHeader(value, version)[0],
        createDecoder=lambda value, recovery: ReleasedDecoder(value, version, recovery))


releasedV0SessionFormatCodec = createReleasedCodec(0)
releasedV1SessionFormatCodec = createReleasedCodec(1)
