"""Observe interleaved stdio frames within one elapsed-time deadline."""
import queue
import time


def wait_frame(frames, observed, predicate, stderr, timeout=10):
    for frame in observed:
        if predicate(frame):
            return frame
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError('SDK response timed out: ' + ''.join(stderr))
        try:
            frame = frames.get(timeout=remaining)
        except queue.Empty:
            raise AssertionError('SDK response timed out: ' + ''.join(stderr))
        assert 'invalid' not in frame and 'eof' not in frame, (frame, stderr)
        observed.append(frame)
        if predicate(frame):
            return frame
