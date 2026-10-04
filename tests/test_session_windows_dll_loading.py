import ctypes

import pytest

from dsh.session import file_revision, sqlite_database


@pytest.mark.parametrize('provider', ['attributes', 'query'])
def test_session_dll_loading_uses_unpatched_windows_loader_flags(monkeypatch, provider):
    original = ctypes._dlopen
    observations = []

    def without_search_directory_patch(path, flags):
        observations.append((path, flags))
        if flags & 0x1f00:
            raise OSError(87, 'simulated Windows 7 without KB2533623 rejects search flags')
        return original(path, flags)

    load = file_revision._windows_api if provider == 'attributes' else sqlite_database._library
    load.cache_clear()
    monkeypatch.setattr(ctypes, '_dlopen', without_search_directory_patch)
    try:
        load()
        assert len(observations) == 1
        assert observations[0][1] == 0
    finally:
        load.cache_clear()
