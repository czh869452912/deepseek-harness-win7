import queue

import pytest

import sdk_stdio_test_support as support


def test_notifications_cannot_extend_the_response_deadline(monkeypatch):
    elapsed = [0.0]
    timeouts = []

    class Notifications(queue.Queue):
        def get(self, timeout):
            timeouts.append(timeout)
            elapsed[0] += 0.04
            return super().get(block=False)

    frames = Notifications()
    for sequence in range(20):
        frames.put(dict(method='session.status', seq=sequence))
    monkeypatch.setattr(support.time, 'monotonic', lambda: elapsed[0])
    observed = []
    with pytest.raises(AssertionError, match='SDK response timed out: actual diagnostic'):
        support.wait_frame(frames, observed, lambda frame: frame.get('id') == 2,
                           ['actual diagnostic'], timeout=0.1)
    assert len(observed) == 3 and frames.qsize() == 17
    assert timeouts == pytest.approx([0.1, 0.06, 0.02])


@pytest.mark.parametrize('frame', [dict(eof=True), dict(invalid='not json')])
def test_protocol_failure_is_not_hidden_by_unmatched_frames(frame):
    frames = queue.Queue()
    frames.put(dict(method='session.status'))
    frames.put(frame)
    with pytest.raises(AssertionError):
        support.wait_frame(frames, [], lambda value: value.get('id') == 2, [])
