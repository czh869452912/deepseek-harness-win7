"""Released v0/v1 admission, with vocabulary and envelope policy kept separate."""
import json
from pathlib import Path

from dsh.core.session.json import UNDEFINED, deep_freeze, is_json_value
from dsh.cordis.utils import _js_strict_equal, js_to_string
from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError, sessionFormatCount, sessionFormatSafeInteger
from .codec import record, exact_keys, assertReleasedSessionFormatHeader
from .payload import assertReleasedPayloadSemantics, compact, SUBAGENT_DESCRIPTOR_VERSIONS

RELEASED_V0_EVENT_DISPOSITIONS = deep_freeze(json.loads(Path(__file__).with_name('dispositions.json').read_text(encoding='utf-8')))
RELEASED_V0_EVENT_TYPES = tuple(sorted(RELEASED_V0_EVENT_DISPOSITIONS))
SURFACE_TYPES = frozenset(('user/message', 'assistant/message', 'tool/result'))
LEGACY_TYPES = frozenset(('steering/message', 'request/header-delta', 'mode/set', 'compact/start', 'compact/summary', 'compact/end', 'compact/prune'))


def assertReleasedV1Header(header):
    assertReleasedSessionFormatHeader(header, 1)


def restoreReleasedV1Artifact(artifact, knownEventTypes):
    assertReleasedV1Header(artifact['header'])
    assertReleasedArtifactCoordinates(artifact, False, knownEventTypes)
    return artifact


def assertReleasedArtifactCoordinates(artifact, allowLegacySteering, knownEventTypes=None, vocabularyNeutral=False, frozenEnvelope=False):
    inherited = sessionFormatCount(artifact.get('inheritedEventCount', UNDEFINED), 'Session inheritedEventCount')
    events = artifact['events']
    if inherited > len(events):
        raise SessionFormatError('Session inheritedEventCount exceeds its event count')
    if not artifact['header']['isSeeded'] and inherited != 0:
        raise SessionFormatError('unseeded Session inheritedEventCount must be 0')
    for index, event in enumerate(events):
        value = record(event, 'Session event %s' % index)
        kind = value.get('type', UNDEFINED)
        if not isinstance(kind, str):
            raise SessionFormatError('Session event %s type must be a string' % index)
        disposition = RELEASED_V0_EVENT_DISPOSITIONS.get(kind)
        legacy = allowLegacySteering and kind in LEGACY_TYPES
        current_known = knownEventTypes is not None and kind in knownEventTypes
        ignorable = not allowLegacySteering and not current_known and value.get('ignorable') is True
        if not current_known and not legacy and not ignorable and not vocabularyNeutral:
            if allowLegacySteering:
                raise SessionFormatUnsupportedMigrationError('format v0 contains unknown historical event type %s at seq %s; migration refuses unknown historical events even when ignorable' % (compact(kind), index))
            raise SessionFormatUnsupportedMigrationError('format v1 contains unknown required event type %s at seq %s' % (compact(kind), index))
        surface = kind in SURFACE_TYPES if disposition is not None else kind == 'steering/message'
        admitted = ['ignorable', 'sourceEventSeqs', 'surfaceOp'] if not frozenEnvelope or surface else ['ignorable']
        exact_keys(value, ['type', 'seq', 'time', 'data'], admitted, 'Session event %s' % index)
        if not _js_strict_equal(value['seq'], index):
            raise SessionFormatError('Session event %s has non-dense seq %s' % (index, compact(value['seq'])))
        sessionFormatSafeInteger(value['time'], 'Session event %s time' % index)
        if value.get('ignorable', UNDEFINED) is not UNDEFINED and value['ignorable'] is not True:
            raise SessionFormatError('Session event %s ignorable must be true when present' % index)
        if frozenEnvelope and surface:
            assertReleasedSurfaceMetadata(value, index, kind, 'allow-empty-assistant')


def assertReleasedSurfaceMetadata(value, seq, kind, assistantSources):
    sources = value.get('sourceEventSeqs', UNDEFINED)
    if kind == 'assistant/message' and sources is not UNDEFINED and assistantSources == 'forbid-assistant':
        raise SessionFormatError('assistant/message %s retains obsolete chunk provenance' % seq)
    if sources is not UNDEFINED:
        if not isinstance(sources, list):
            raise SessionFormatError('%s %s sourceEventSeqs must be an array' % (kind, seq))
        seen = set()
        for source in sources:
            current = sessionFormatCount(source, '%s %s sourceEventSeqs member' % (kind, seq))
            if current >= seq or current in seen:
                raise SessionFormatError('%s %s sourceEventSeqs must be unique earlier seqs' % (kind, seq))
            seen.add(current)
        if not sources and kind != 'assistant/message':
            raise SessionFormatError('%s %s sourceEventSeqs must be non-empty' % (kind, seq))
    operation = value.get('surfaceOp', UNDEFINED)
    if operation is UNDEFINED or operation == 'append':
        return
    replacement = record(operation, '%s %s surfaceOp' % (kind, seq))
    exact_keys(replacement, ['op', 'start', 'end'], [], '%s %s surfaceOp' % (kind, seq))
    if replacement['op'] != 'replace':
        raise SessionFormatError('%s %s surfaceOp must replace' % (kind, seq))
    start = sessionFormatCount(replacement['start'], '%s %s surface start' % (kind, seq))
    end = sessionFormatCount(replacement['end'], '%s %s surface end' % (kind, seq))
    if start >= seq or end >= seq:
        raise SessionFormatError('%s %s has an invalid surface replacement' % (kind, seq))


def assertReleasedEventPayload(event, version):
    kind, seq = event['type'], js_to_string(event['seq'])
    disposition = RELEASED_V0_EVENT_DISPOSITIONS.get(kind)
    if disposition is None:
        raise SessionFormatUnsupportedMigrationError('format v0 contains unknown historical event type %s at seq %s; migration refuses unknown historical events even when ignorable' % (compact(kind), seq))
    data = record(event['data'], '%s %s data' % (kind, seq))
    if kind == 'subagent/descriptor' and not any(_js_strict_equal(data.get('version', UNDEFINED), known)
                                              for known in SUBAGENT_DESCRIPTOR_VERSIONS):
        descriptor_version = sessionFormatCount(data.get('version', UNDEFINED), '%s %s version' % (kind, seq))
        if version == 0:
            raise SessionFormatUnsupportedMigrationError('%s %s uses unsupported descriptor version %s' % (kind, seq, js_to_string(descriptor_version)))
        return
    admitted = list(disposition['optional'])
    if version == 1 and kind == 'session-log-deepseek/delivery-accepted':
        admitted.append('sessionFormatVersion')
    exact_keys(data, disposition['required'], admitted, '%s %s data' % (kind, seq))
    for key in disposition['opaque']:
        if key in data and not is_json_value(data[key]):
            raise SessionFormatError('%s %s opaque %s is not lossless JSON' % (kind, seq, key))
    assertReleasedPayloadSemantics(event, version)
