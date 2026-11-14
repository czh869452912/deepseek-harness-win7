"""Explicit edge composition and native framing without production promotion."""
import copy

import pytest

from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError
from dsh.session.format.chain import SessionFormatEventCollector
from dsh.session.format_v3_to_v4 import (
    createSessionFormatV3ToV4, sessionFormatV3ToV4, releasedV4SessionFormatCodec,
    restoreReleasedV4Artifact, assertV4RowAdmission, RELEASED_V3_EVENT_TYPES,
)


def header(version=3, **extra):
    return dict(version=version, id='parent', createdAt=1, isSeeded=False, delegationDepth=0, **extra)


def events(rows):
    return [dict(value, seq=index, time=index+10) for index, value in enumerate(rows)]


def row(event_type, **data):
    return dict(type=event_type, data=data)


def stage(rows, children=(), physical=None, **extra):
    physical = physical or header()
    declaration = createSessionFormatV3ToV4(children)
    context = SessionFormatEventCollector()
    transform = declaration['createStage'](dict(sourceHeader=physical, **extra))
    for event in events(rows):
        transform.transformEvent(event, context)
    return dict(header=declaration['migrateHeader'](physical), events=context.values,
                inheritedEventCount=transform.finish(context))


def test_unbound_edge_requires_an_explicit_empty_child_declaration():
    assert sessionFormatV3ToV4['migrateHeader'](header())['version'] == 4
    with pytest.raises(SessionFormatUnsupportedMigrationError, match='explicit historical child facts'):
        sessionFormatV3ToV4['createStage'](dict(sourceHeader=header()))
    assert stage([])['events'] == []


def test_restart_closes_only_evidenced_turn_and_remaps_following_local_reference():
    user = dict(id='u', role='user', source=dict(kind='user'), content=[])
    source = [row('turn/start', turn=1), row('step/start', turn=1, step=1), row('step/end', turn=1, step=1),
        row('agent/inbox/spliced', target='next-turn', inserted=[user]), row('turn/start', turn=2),
        row('command/run', commandId='cmd'), row('command/done', commandId='cmd', kind='success', sourceEventSeq=4),
        row('turn/end', turn=2)]
    before = copy.deepcopy(source)
    artifact = stage(source)
    assert artifact['events'][4] == dict(type='turn/end', seq=4, time=14, data=dict(turn=1, reason=dict(kind='interrupted')))
    assert artifact['events'][7]['data']['sourceEventSeq'] == 5
    assert [value['seq'] for value in artifact['events']] == list(range(9))
    assert source == before
    restoreReleasedV4Artifact(artifact, RELEASED_V3_EVENT_TYPES)


def test_open_step_prevents_restart_repair_instead_of_hiding_invalid_boundary():
    source = [row('turn/start', turn=1), row('step/start', turn=1, step=1),
        row('agent/inbox/spliced', target='next-turn', inserted=[dict(id='u', role='user', source={'kind':'user'}, content=[])]),
        row('turn/start', turn=2)]
    artifact = stage(source)
    assert len(artifact['events']) == 4
    with pytest.raises(SessionFormatError, match='expected turn'):
        restoreReleasedV4Artifact(artifact, RELEASED_V3_EVENT_TYPES)


def test_child_facts_are_sorted_completed_and_stages_do_not_share_mutable_state():
    children = [dict(childId='late', childCreatedAt=2, descriptorCount=0, descriptor=None),
        dict(childId='early', childCreatedAt=1, descriptorCount=1, descriptor=dict(version=1, provider='p', label='child'))]
    declaration = createSessionFormatV3ToV4(children)
    first = declaration['createStage'](dict(sourceHeader=header()))
    second = declaration['createStage'](dict(sourceHeader=header()))
    context = SessionFormatEventCollector(); first.finish(context)
    other = SessionFormatEventCollector(); second.finish(other)
    assert context.values == other.values
    assert [value['data']['childId'] for value in context.values] == ['early', 'late']
    assert context.values[1]['data']['mode'] == 'unknown'
    assert context.values[0]['data']['label'] == 'child'


def test_existing_own_catalog_conflicts_are_not_silently_overwritten():
    child = dict(childId='c', childCreatedAt=1, descriptorCount=1, descriptor=dict(version=1, provider='p', label='child'))
    with pytest.raises(SessionFormatUnsupportedMigrationError, match='conflicts with its parent catalog'):
        stage([row('subagent/catalog', version=0, childId='c', childCreatedAt=1, mode='continuable', label='other')], [child])


def test_inherited_catalog_does_not_replace_the_current_generations_child_evidence():
    physical = dict(header(), isSeeded=True, parentSession='p')
    child = dict(childId='c', childCreatedAt=1, descriptorCount=0, descriptor=None)
    result = stage([row('subagent/catalog', version=1, childId='c', childCreatedAt=99, mode='unknown'),
                    row('session/end-seed', inherited=True)], [child], physical, sourceInheritedEventCount=1)
    assert result['inheritedEventCount'] == 1
    assert result['events'][-1]['data']['childCreatedAt'] == 1


def test_opaque_event_retains_unvalidated_references_across_restart_insertion():
    user = dict(id='u', role='user', source={'kind':'user'}, content=[])
    opaque = dict(type='extension', ignorable=True, data={'seq':4}, sourceEventSeqs='opaque', surfaceOp={'custom':True})
    result = stage([row('turn/start',turn=1),row('agent/inbox/spliced',target='next-turn',inserted=[user]),
                    row('turn/start',turn=2),opaque])
    event = result['events'][-1]
    assert event['type'] == 'plugin:extension' and event['seq'] == 4
    assert event['data'] == {'seq':4} and event['sourceEventSeqs'] == 'opaque'


def test_physical_recovery_cannot_discard_retired_syntax_after_a_broken_tail():
    physical = dict(type='session', **header(4))
    decoder = releasedV4SessionFormatCodec['createDecoder'](physical, 'recover-tail')
    collector = SessionFormatEventCollector()
    decoder.decodeRow({'broken':True}, collector)
    with pytest.raises(SessionFormatError, match='header.system'):
        decoder.decodeRow(dict(type='request/header', data=dict(header=dict(system=None))), collector)


def test_unknown_ignorable_developer_record_is_deferred_to_reader_vocabulary():
    event = dict(type='developer/message', seq=0, time=1, data=[], ignorable=True)
    assertV4RowAdmission(event)
    with pytest.raises(SessionFormatError, match='data must be an object'):
        assertV4RowAdmission(event, {'developer/message'})
    with pytest.raises(SessionFormatError, match='data must be an object'):
        releasedV4SessionFormatCodec['encodeEvent'](event)


def test_catalog_names_are_unique_only_for_current_generation():
    def catalog(identity):
        return row('subagent/catalog',version=3,childId=identity,childCreatedAt=1,mode='external',name='child')
    artifact = dict(header=header(4),inheritedEventCount=0,events=events([catalog('a'),catalog('b')]))
    with pytest.raises(SessionFormatError, match='duplicate catalog child name'):
        restoreReleasedV4Artifact(artifact, RELEASED_V3_EVENT_TYPES)
