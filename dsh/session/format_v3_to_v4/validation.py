"""Native V4 header and delivery ownership, independent of physical recovery."""
import os
import re

from dsh.core.session.json import UNDEFINED
from dsh.cordis.utils import _js_strict_equal
from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError, sessionFormatCount
from dsh.session.format_v0_to_v1.payload import compact
from .developer import assertV4DeveloperData
from .facts import catalogFact
from .fork_result import assertV4ForkResult
from .message_sources import assertV4MessageSources
from .retired_syntax import assertV4RetiredSyntax
from .system_message import assertV4SystemMessageFields
from .tool_role import assertV4ToolResultMessage


def assertReleasedV4Header(header):
    if not isinstance(header, dict) or not _js_strict_equal(header.get('version', UNDEFINED), 4):
        raise SessionFormatError('expected format v4 header')
    required = ('version', 'id', 'createdAt', 'isSeeded', 'delegationDepth')
    allowed = set(required) | {'cwd', 'parentSession', 'origin', 'agentPreset'}
    missing = next((key for key in required if key not in header), None)
    unexpected = next((key for key in header if key not in allowed), None)
    if missing is not None:
        raise SessionFormatError('format v4 header lacks required field ' + missing)
    if unexpected is not None:
        raise SessionFormatError('format v4 header has unexpected field ' + unexpected)
    if not isinstance(header['id'], str):
        raise SessionFormatError('format v4 header id must be a string')
    sessionFormatCount(header['createdAt'], 'format v4 header createdAt')
    sessionFormatCount(header['delegationDepth'], 'format v4 header delegationDepth')
    if type(header['isSeeded']) is not bool:
        raise SessionFormatError('format v4 header isSeeded must be boolean')
    if header.get('cwd', UNDEFINED) is not UNDEFINED and (not isinstance(header['cwd'], str) or not os.path.isabs(header['cwd'])):
        raise SessionFormatError('format v4 header cwd must be absolute')
    for key in ('parentSession', 'agentPreset'):
        if header.get(key, UNDEFINED) is not UNDEFINED and not isinstance(header[key], str):
            raise SessionFormatError('format v4 header ' + key + ' must be a string')
    if header.get('origin', UNDEFINED) is not UNDEFINED and header['origin'] != 'subagent':
        raise SessionFormatError('format v4 header origin must be "subagent"')


def validateDeliveryAccepted(event, currentVersion):
    if event['type'] != 'session-log-deepseek/delivery-accepted':
        return None
    data = event['data']
    if not isinstance(data, dict):
        raise SessionFormatError('delivery-accepted data must be an object')
    version = sessionFormatCount(data.get('sessionFormatVersion', 0), 'delivery sessionFormatVersion')
    if not _js_strict_equal(version, currentVersion):
        return None
    through = sessionFormatCount(data.get('throughSeq', UNDEFINED), 'delivery throughSeq')
    if through >= event['seq']:
        raise SessionFormatError('delivery throughSeq must precede its marker')
    identity = data.get('sessionId')
    if not isinstance(identity, str) or not identity:
        raise SessionFormatError('delivery requires a nonempty Session id')
    return identity


def _native_catalog_fact(value):
    if not isinstance(value, dict) or not _js_strict_equal(value.get('version', UNDEFINED), 3):
        return catalogFact(value)
    if (not isinstance(value.get('childId'), str) or value.get('mode') not in ('continuable', 'external')
            or not isinstance(value.get('name'), str) or re.fullmatch(r'[a-z][a-z0-9-]{0,31}', value['name']) is None
            or value['name'] == 'lead' or value.get('mode') == 'continuable' and not isinstance(value.get('label'), str)
            or value.get('label', UNDEFINED) is not UNDEFINED and not isinstance(value['label'], str)):
        raise SessionFormatError('subagent/catalog requires a supported versioned catalog fact')
    sessionFormatCount(value.get('childCreatedAt', UNDEFINED), 'catalog child creation time')
    return value


def restoreReleasedV4Artifact(artifact, knownEventTypes):
    assertReleasedV4Header(artifact['header'])
    cut = sessionFormatCount(artifact['inheritedEventCount'], 'format v4 inherited event count')
    if cut > len(artifact['events']):
        raise SessionFormatError('format v4 inherited event count exceeds its events')
    if not artifact['header']['isSeeded'] and cut != 0:
        raise SessionFormatError('unseeded format v4 Session has inherited events')
    marker = UNDEFINED
    for index, event in enumerate(artifact['events']):
        if event['type'] not in knownEventTypes and event.get('ignorable') is not True:
            raise SessionFormatUnsupportedMigrationError('format v4 contains unknown event type ' + compact(event['type']) + ' at seq ' + str(index))
        if not _js_strict_equal(event['seq'], index):
            raise SessionFormatError('format v4 event ' + str(index) + ' is not dense')
        if event['type'] not in knownEventTypes:
            continue
        assertV4RetiredSyntax(event)
        assertV4SystemMessageFields(event)
        assertV4ToolResultMessage(event)
        assertV4ForkResult(event)
        if event['type'] == 'session/end-seed' and isinstance(event['data'], dict) and event['data'].get('inherited') is True:
            marker = index
    if artifact['header']['isSeeded'] and not _js_strict_equal(marker, cut):
        raise SessionFormatError('format v4 seeded header disagrees with its last inherited end-seed marker')
    if not artifact['header']['isSeeded'] and marker is not UNDEFINED:
        raise SessionFormatError('format v4 unseeded Session contains an inherited end-seed marker')
    assertReleasedV4Relationships(artifact, knownEventTypes)
    return artifact


def assertReleasedV4Relationships(artifact, knownEventTypes):
    from .relationships import assertV4LifecycleRelationships
    identities, names = set(), set()
    for event in artifact['events']:
        if event['type'] not in knownEventTypes:
            continue
        assertV4DeveloperData(event)
        assertV4MessageSources(event)
        delivery_id = validateDeliveryAccepted(event, 4)
        if delivery_id is not None and event['seq'] >= artifact['inheritedEventCount'] and delivery_id != artifact['header']['id']:
            raise SessionFormatError('current-generation delivery marker names the wrong Session')
        if event['type'] == 'subagent/catalog' and event['seq'] >= artifact['inheritedEventCount']:
            fact = _native_catalog_fact(event['data']); identity = fact['childId']
            if identity in identities:
                raise SessionFormatError('duplicate catalog child ' + identity)
            identities.add(identity)
            if fact.get('name', UNDEFINED) is UNDEFINED:
                continue
            name = fact['name']
            if name in names:
                raise SessionFormatError('duplicate catalog child name ' + name)
            names.add(name)
    assertV4LifecycleRelationships(artifact, knownEventTypes)
