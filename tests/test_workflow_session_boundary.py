import pytest

from scripts.oracles.workflow_session_boundary import WorkflowSessionBoundary


@pytest.mark.parametrize('semantic', ['agent-end', 'log'])
@pytest.mark.parametrize('order', ['semantic-first', 'dispose-first'])
def test_dropped_child_observation_requires_result_semantics_and_disposal(semantic, order):
    name = 'dropped-child-continuation' if semantic == 'log' else 'dropped-child-after-result'
    recorder = WorkflowSessionBoundary(dict(name=name, waitDisposals=1))
    recorder.record(dict(type='ready'))
    recorder.record(dict(type='child-start', callId=1))
    assert not recorder.record(dict(type='result', result=dict(value='done')))
    events = [dict(type=semantic), dict(type='child-dispose', callId=1)]
    if order == 'dispose-first':
        events.reverse()
    assert not recorder.record(events[0])
    assert recorder.record(events[1])
    assert recorder.snapshot == recorder.frames
    assert recorder.snapshot is not recorder.frames
    recorder.record(dict(type='late-diagnostic', message='raw retained'))
    assert len(recorder.frames) == 6 and len(recorder.snapshot) == 5
    assert recorder.frames[-1]['message'] == 'raw retained'


def test_duplicate_disposal_never_satisfies_another_owned_child():
    recorder = WorkflowSessionBoundary(dict(name='dropped-child-after-result', waitDisposals=2))
    recorder.record(dict(type='result'))
    recorder.record(dict(type='agent-end'))
    assert not recorder.record(dict(type='child-dispose', callId=1))
    assert not recorder.record(dict(type='child-dispose', callId=1))
    assert recorder.record(dict(type='child-dispose', callId=2))
    assert len(recorder.snapshot) == 5


def test_semantics_and_disposal_without_terminal_result_never_complete():
    recorder = WorkflowSessionBoundary(dict(name='dropped-child-after-result', waitDisposals=1))
    assert not recorder.record(dict(type='agent-end'))
    assert not recorder.record(dict(type='child-dispose', callId=1))
    assert recorder.record(dict(type='result'))


def test_recorded_frame_and_snapshot_do_not_alias_mutable_transport_payload():
    recorder = WorkflowSessionBoundary(dict(name='ordinary'))
    payload = dict(type='result', result=dict(value=[1]))
    assert recorder.record(payload)
    payload['result']['value'].append(2)
    assert recorder.snapshot[0]['result']['value'] == [1]
    assert recorder.frames[0]['result']['value'] == [1]


@pytest.mark.parametrize('count', [-1, True, '1'])
def test_invalid_expected_disposal_count_is_refused(count):
    with pytest.raises(ValueError):
        WorkflowSessionBoundary(dict(name='ordinary', waitDisposals=count))
