import asyncio
import json
import os
import subprocess
import sys

import pytest
from dsh.cordis.file_lock import with_file_lock

from scripts.rc022_local_credentials_probe import observe


@pytest.mark.asyncio
async def test_managed_credential_reference_and_preview_corpus(tmp_path):
    rows = await observe(tmp_path/'files')
    (tmp_path/'local-credentials-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 60
    for row in rows:
        initial, saved, removed, absent, rejected = row['result']
        assert initial['events'] == []
        assert saved['value']['source'] == 'file' and saved['info']['writable'] is True
        assert saved['info']['masked'] != saved['value']['value']
        assert 'masked' not in removed['info']
        assert absent == removed
        assert absent['events'] == ['TEST_KEY', 'TEST_KEY']
        assert row['refs'] == {}
        assert rejected['error'].endswith('; use unset')


@pytest.mark.skipif(os.name != 'nt', reason='Legacy Windows CRT lock marker')
@pytest.mark.asyncio
async def test_legacy_lock_marker_waits_for_active_owner(tmp_path):
    lock = tmp_path / '.credentials.yaml.lock'
    ready = tmp_path / 'ready'
    owner = subprocess.Popen([sys.executable, '-c', '''
import msvcrt
import sys
from pathlib import Path
with open(sys.argv[1], 'w+b') as marker:
    marker.write(b'\\0')
    marker.flush()
    marker.seek(0)
    msvcrt.locking(marker.fileno(), msvcrt.LK_NBLCK, 1)
    Path(sys.argv[2]).touch()
    sys.stdin.buffer.read(1)
''', str(lock), str(ready)], stdin=subprocess.PIPE)
    calls = []
    try:
        for _ in range(100):
            if ready.exists() or owner.poll() is not None:
                break
            await asyncio.sleep(.05)
        assert ready.exists() and owner.poll() is None
        with pytest.raises(RuntimeError, match='timed out'):
            await with_file_lock(str(lock), lambda: calls.append('early'), waitMs=20, legacy_windows_marker=True)
        assert calls == []
    finally:
        try:
            owner.communicate(b'1', timeout=10)
        except subprocess.TimeoutExpired:
            owner.kill()
            owner.communicate(timeout=10)
            raise
    assert owner.returncode == 0

    def acquired():
        # Older CRT writers cannot even open the file while this callback runs.
        with pytest.raises(PermissionError):
            lock.open('r+b')
        return 'acquired'

    assert await with_file_lock(str(lock), acquired, waitMs=20, legacy_windows_marker=True) == 'acquired'
    assert lock.read_bytes() == b'\0'
    lock.write_bytes(b'123\n')
    with pytest.raises(RuntimeError, match='timed out'):
        await with_file_lock(str(lock), acquired, waitMs=20, legacy_windows_marker=True)
    assert lock.read_bytes() == b'123\n'
