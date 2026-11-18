"""Released semantic rules and actual upstream restore calls, frozen at rc.3."""
import json
import hashlib
from pathlib import Path

import pytest

from dsh.session.format import SessionFormatError, SessionFormatEventCollector
from dsh.session.format_v0_to_v1 import (sessionFormatV0ToV1,
    releasedV0SessionFormatCodec, restoreReleasedV1Artifact, assertReleasedArtifactRelationships)
from scripts.oracles.session_format_python import observe
from scripts.session_format_oracle import json_equal

ROOT = Path(__file__).resolve().parents[1]
CASES = []
for name in ('session_released_payload_cases.json', 'session_released_restore_cases.json'):
    CASES.extend(json.loads((ROOT / 'scripts/oracles' / name).read_text(encoding='utf-8')))
CURRENT = json.loads((ROOT / 'tests/fixtures/rc022-released-logical-deltas.json').read_text(encoding='utf-8'))
CURRENT_DELTAS = {row['case']: row for row in CURRENT['current_deltas']}


def test_current_released_logical_deltas_keep_original_facts_and_exact_inputs():
    assert CURRENT['target_upstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert CURRENT['observations'] == len(CASES)
    assert set(CURRENT_DELTAS) == {'subagent/descriptor/omit/mode', 'subagent/descriptor/omit/label'}
    for path, digest in CURRENT['inputs'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    for case in CASES:
        if case['case'] in CURRENT_DELTAS:
            assert dict(case['expected'], case=case['case']) != CURRENT_DELTAS[case['case']]


@pytest.mark.parametrize('case', CASES, ids=[case['case'] for case in CASES])
def test_released_logical_source_observations(case):
    expected = CURRENT_DELTAS.get(case['case'], dict(case['expected'], case=case['case']))
    # Compare the same wire observations as the paired subprocess runner. Frozen
    # containers in native memory are an additional guarantee, not a JSON type.
    actual = json.loads(json.dumps(observe(case)))
    assert json_equal(actual, expected)


def source_input(**values):
    return dict(sourceHeader=dict(version=0, id='logical', createdAt=1, isSeeded=False, delegationDepth=0),
        sourceInheritedEventCount=0, sourceKind='decoded', **values)


def test_v0_stage_preserves_compact_runs_without_eager_expansion():
    decoder = releasedV0SessionFormatCodec['createDecoder'](dict(type='session', version=0,
        id='logical', createdAt=1, delegationDepth=0), 'strict')
    runs = []
    class Context:
        def emitRun(self, run):
            runs.append(run)
        def emitEvent(self, event):
            pytest.fail('Compact chunk runs must stay compact across the identity edge')
    context = Context()
    decoder.decodeRow(dict(type='text-chunks', seq0=0, time0=1,
        data=dict(turn=1, step=1, index=0, dt=[1, 1], texts=['a', 'b', 'c'])), context)
    run = runs.pop()
    stage = sessionFormatV0ToV1['createStage'](source_input())
    stage.transformRun(run, context)
    assert runs == [run]
    assert runs[0] is run
    assert stage.finish(context) == 0


def test_v0_stage_transformed_inputs_are_detached_and_keep_replacement_identity():
    stage = sessionFormatV0ToV1['createStage'](source_input())
    collector = SessionFormatEventCollector()
    original = dict(type='tool/result', seq=0, time=1, surfaceOp='append',
        data=dict(turn=1, step=1, callId='c', content=[], isError=False))
    stage.transformEvent(original, collector)
    replacement = dict(original, seq=1, surfaceOp=dict(op='replace', start=0, end=0), sourceEventSeqs=[0])
    stage.transformEvent(replacement, collector)
    assert 'message' not in original['data']
    assert [event['data']['message']['id'] for event in collector.values] == ['legacy-message:logical:0'] * 2


def test_current_v1_restorer_uses_installed_vocabulary_without_freezing_plugin_payloads():
    artifact = dict(header=dict(version=1, id='current', createdAt=1, isSeeded=False, delegationDepth=0),
        inheritedEventCount=0, events=[dict(type='installed/extension', seq=0, time=1, data=dict(newField=True))])
    assert restoreReleasedV1Artifact(artifact, {'installed/extension'}) is artifact


def test_ptc_opaque_json_is_structural_and_keeps_booleans_distinct_from_numbers():
    def event(kind, seq, data):
        return dict(type=kind, seq=seq, time=seq, data=data)
    data = dict(rootCallId='r', parentCallId='r', subCallId='s', name='read', arguments={'first': [True], 'second': 1})
    events = [event('turn/start', 0, dict(turn=1)), event('tool/code-dispatch-start', 1, data),
        event('tool/code-dispatch', 2, dict(data, arguments={'second': 1.0, 'first': [True]}, isError=False, content=[]))]
    artifact = dict(events=events, header=dict(version=1, id='ptc', isSeeded=False), inheritedEventCount=0)
    assertReleasedArtifactRelationships(artifact)
    events[-1]['data']['arguments']['first'] = [1]
    with pytest.raises(SessionFormatError, match='does not match its start'):
        assertReleasedArtifactRelationships(artifact)
