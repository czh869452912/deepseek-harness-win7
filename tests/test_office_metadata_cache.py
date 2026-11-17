import os

import pytest

from dsh.core.abort import AbortController
from dsh.office.metadata_cache import read_cache, publish_cache


def test_optional_bounded_stable_cache_read(tmp_path):
    signal = AbortController().signal
    assert read_cache(False, 8, signal) is None
    assert read_cache(str(tmp_path), 8, signal) is None
    path = tmp_path / 'font-metadata.json'
    path.write_bytes(b'cached')
    assert read_cache(str(tmp_path), 8, signal) == b'cached'
    assert read_cache(str(tmp_path), 5, signal) is None
    path.write_bytes(b'')
    assert read_cache(str(tmp_path), 8, signal) is None


def test_publish_is_bounded_atomic_and_removes_owned_temporary(tmp_path):
    signal = AbortController().signal
    directory = tmp_path / 'cache'
    publish_cache(str(directory), b'first', 8, signal)
    path = directory / 'font-metadata.json'
    assert path.read_bytes() == b'first'
    publish_cache(str(directory), b'next', 8, signal)
    assert path.read_bytes() == b'next'
    publish_cache(str(directory), b'oversized', 8, signal)
    publish_cache(str(directory), None, 8, signal)
    assert path.read_bytes() == b'next'
    assert list(directory.iterdir()) == [path]


def test_optional_publish_failure_keeps_previous_cache(tmp_path, monkeypatch):
    path = tmp_path / 'font-metadata.json'
    path.write_bytes(b'previous')
    def failed(*args):
        raise PermissionError('read only cache')
    monkeypatch.setattr(os, 'replace', failed)
    publish_cache(str(tmp_path), b'next', 8, AbortController().signal)
    assert path.read_bytes() == b'previous'
    assert list(tmp_path.iterdir()) == [path]


def test_cancelled_publish_keeps_previous_cache_and_unlinks_owned_file(tmp_path, monkeypatch):
    path = tmp_path / 'font-metadata.json'
    path.write_bytes(b'previous')
    controller = AbortController()
    reason = RuntimeError('scan stopped')
    original = os.fdopen
    class Writer:
        def __init__(self, descriptor, mode):
            self.stream = original(descriptor, mode)
        def __enter__(self):
            return self
        def write(self, data):
            self.stream.write(data)
            controller.abort(reason)
        def __exit__(self, *args):
            self.stream.close()
    monkeypatch.setattr(os, 'fdopen', Writer)
    with pytest.raises(RuntimeError) as caught:
        publish_cache(str(tmp_path), b'next', 8, controller.signal)
    assert caught.value is reason
    assert path.read_bytes() == b'previous'
    assert list(tmp_path.iterdir()) == [path]
