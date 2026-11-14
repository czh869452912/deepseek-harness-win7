"""Child evidence ownership, reference coordinates and fork-result provenance."""
import copy

import pytest

from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError
from dsh.session.format_v3_to_v4.facts import childCatalogSource, childCatalogFact, historicalChildCatalogSource
from dsh.session.format_v3_to_v4.fork_result import assertV4ForkResult
from dsh.session.format_v3_to_v4.references import remapV3References
from dsh.session.format_v3_to_v4.extension_identities import namespaceV3OpaqueEvent


def test_child_uses_only_own_descriptor_after_the_final_inherited_cut():
    inherited = dict(type='subagent/descriptor', seq=0, data=dict(version=1, provider='p', label='inherited'))
    own = dict(type='subagent/descriptor', seq=2, data=dict(version=3, provider='p', mode='one-shot', extra={'opaque': 1}))
    artifact = dict(header=dict(id='child', origin='subagent', parentSession='parent', createdAt=9),
                    inheritedEventCount=2, events=[inherited, dict(type='session/end-seed', seq=1, data={}), own])
    before = copy.deepcopy(artifact)
    source = historicalChildCatalogSource(artifact)
    assert source['descriptorCount'] == 1 and source['descriptor'] is own['data']
    assert childCatalogFact(source) == dict(version=0, childId='child', childCreatedAt=9, mode='one-shot')
    assert artifact == before
    artifact['inheritedEventCount'] = 3
    assert childCatalogFact(historicalChildCatalogSource(artifact)) is None


def test_child_evidence_admits_unknown_descriptor_without_interpreting_its_payload():
    source = dict(childId='child', childCreatedAt=0, descriptorCount=1, descriptor=dict(version=99, provider=False))
    assert childCatalogSource(source) is source
    assert childCatalogFact(source) is None
    source['descriptor']['version'] = 1
    source['sourcePath'] = 'C:/logs/child'
    with pytest.raises(SessionFormatUnsupportedMigrationError, match=r'Session child \(raw log: C:/logs/child\).*provider'):
        childCatalogFact(source)


def test_duplicate_child_descriptors_do_not_choose_an_arbitrary_identity():
    source = dict(childId='child', childCreatedAt=0, descriptorCount=2,
                  descriptor=dict(version=1, provider='p', label='first'))
    assert childCatalogFact(source) is None


def test_reference_remap_changes_local_coordinates_but_preserves_captures_and_numeric_payloads():
    capture = dict(generation='g', seq=1)
    row = dict(type='image/offload', seq=3, data=dict(targets=[dict(seq=1, bytes=1, capture=capture)]),
               surfaceOp=dict(op='replace', startSeq=1, endSeq=2), sourceEventSeqs=[1, 2])
    before = copy.deepcopy(row)
    target = remapV3References(row, 4, [0, 2, 3])
    assert target['seq'] == 4 and target['data']['targets'][0]['seq'] == 2
    assert target['data']['targets'][0]['bytes'] == 1
    assert target['data']['targets'][0]['capture'] is capture
    assert target['sourceEventSeqs'] == [2, 3]
    assert target['surfaceOp'] == dict(op='replace', startSeq=2, endSeq=3)
    assert row == before
    assert remapV3References(row, 3, []) is row
    row['data']['targets'][0]['seq'] = 1.0
    assert remapV3References(row, 4, [0, 2, 3])['data']['targets'][0]['seq'] == 2


@pytest.mark.parametrize('reference', [False, True, -1, 1.5, 3, 9])
def test_moved_references_require_earlier_source_events(reference):
    row = dict(type='command/done', seq=3, data=dict(sourceEventSeq=reference))
    with pytest.raises(SessionFormatError):
        remapV3References(row, 4, [0, 2, 3])


def test_unknown_ignorable_event_keeps_opaque_coordinates_under_one_incoming_namespace():
    row = dict(type='plugin:custom', seq=3, time=4, ignorable=True,
               data={'seq': 3}, surfaceOp={'not': 'native'}, sourceEventSeqs='opaque')
    value = namespaceV3OpaqueEvent(row)
    assert value['type'] == 'plugin:plugin:custom'
    assert value['data'] is row['data'] and value['surfaceOp'] is row['surfaceOp']
    assert value['sourceEventSeqs'] == 'opaque'
    released = dict(row, type='user/message')
    assert namespaceV3OpaqueEvent(released) is released


def fork():
    return dict(type='tool/result', seq=2, surfaceOp='append', data=dict(
        error=dict(code='TOOL_NOT_STARTED', name='ToolNotStartedError'), message=dict(
            id='forked-tool-result-call-2', role='tool', isError=True,
            source=dict(kind='tool', callId='call'), toolCallId='call', content=[dict(type='text', text='kept')])))


def test_append_fork_identity_uses_own_seq_replacement_uses_one_earlier_source():
    row = fork(); before = copy.deepcopy(row)
    assertV4ForkResult(row)
    assert row == before
    row.update(seq=3, surfaceOp=dict(op='replace'), sourceEventSeqs=[2])
    assertV4ForkResult(row)
    row['sourceEventSeqs'] = [1]
    with pytest.raises(SessionFormatError, match='not-started fork result'):
        assertV4ForkResult(row)


@pytest.mark.parametrize('suffix', ['02', '-2', '2.0', '9007199254740992'])
def test_fork_identity_suffix_is_canonical_safe_integer(suffix):
    row = fork(); row['data']['message']['id'] = 'forked-tool-result-call-' + suffix
    with pytest.raises(SessionFormatError, match='not-started fork result'):
        assertV4ForkResult(row)
