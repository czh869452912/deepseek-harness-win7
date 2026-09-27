"""Windows CRT lock creation can observe a preceding writer's pending delete."""
import errno
import os
import pytest
from dsh.settings.settings_file import _WriterLock


@pytest.mark.skipif(os.name != 'nt', reason='Windows CRT exclusive-create adaptation')
def test_delete_pending_lock_retries_and_then_owns_a_new_lock(tmp_path, monkeypatch):
    path = str(tmp_path / 'settings.lock')
    real_open = os.open
    attempts = []
    def open_lock(name, *args):
        if name == path:
            attempts.append(name)
            if len(attempts) == 1:
                raise PermissionError(errno.EACCES, 'delete pending', name)
        return real_open(name, *args)
    monkeypatch.setattr(os, 'open', open_lock)
    with _WriterLock(path):
        assert os.path.isfile(path)
    assert len(attempts) == 2
    assert not os.path.exists(path)


@pytest.mark.skipif(os.name != 'nt', reason='Windows CRT exclusive-create adaptation')
def test_real_permission_denial_is_not_converted_to_lock_timeout(tmp_path, monkeypatch):
    error = PermissionError(errno.EACCES, 'access denied')
    def denied(*args):
        raise error
    monkeypatch.setattr(os, 'open', denied)
    with pytest.raises(PermissionError) as raised:
        with _WriterLock(str(tmp_path / 'settings.lock'), timeout=0):
            pytest.fail('permission denial cannot acquire a lock')
    assert raised.value is error
