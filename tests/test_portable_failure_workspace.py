import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from scripts.verify_portable import verification_workspace


def test_failed_runtime_retains_actual_observation_and_first_outcome(tmp_path):
    report = {}
    output = tmp_path / 'portable.json'
    with pytest.raises(RuntimeError, match='first runtime failure'):
        with verification_workspace(output, report) as private:
            selected = Path(private)
            (selected / 'observed.bin').write_bytes(b'actual failure observation\x00')
            raise RuntimeError('first runtime failure')
    try:
        assert selected.is_dir()
        receipt = json.loads(output.with_suffix('.failure-workspace.json').read_text(encoding='utf-8'))
        assert receipt['firstFailure'] == dict(name='RuntimeError', message='first runtime failure')
        assert receipt['files']['observed.bin']['sha256'] == hashlib.sha256(b'actual failure observation\x00').hexdigest()
        assert report['workspaceRetention'] == 'retained-after-failure'
    finally:
        shutil.rmtree(str(selected))


def test_successful_private_workspace_is_removed(tmp_path):
    report = {}
    with verification_workspace(tmp_path / 'portable.json', report) as private:
        selected = Path(private)
        (selected / 'reconstructible.txt').write_text('fixture', encoding='utf-8')
    assert not selected.exists()
    assert report['workspaceRetention'] == 'removed-after-success'
    assert not (tmp_path / 'portable.failure-workspace.json').exists()


def test_retention_diagnostic_failure_preserves_primary_exception(tmp_path):
    report = {}
    output = tmp_path / 'portable.json'
    output.with_suffix('.failure-workspace.json').write_text('earlier observation', encoding='utf-8')
    with pytest.raises(ValueError, match='primary'):
        with verification_workspace(output, report) as private:
            selected = Path(private)
            raise ValueError('primary')
    try:
        assert selected.is_dir()
        assert report['workspaceRetentionDiagnostic']['name'] == 'FileExistsError'
        assert output.with_suffix('.failure-workspace.json').read_text(encoding='utf-8') == 'earlier observation'
    finally:
        shutil.rmtree(str(selected))


@pytest.mark.skipif(os.name != 'nt', reason='actual Windows junction boundary')
def test_failure_inventory_does_not_follow_junction(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.txt').write_text('external observation', encoding='utf-8')
    output = tmp_path / 'portable.json'
    report = {}
    with pytest.raises(RuntimeError, match='junction failure'):
        with verification_workspace(output, report) as private:
            selected = Path(private)
            link = selected / 'opaque'
            result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(outside)],
                                    capture_output=True, timeout=10)
            assert result.returncode == 0, result.stderr
            raise RuntimeError('junction failure')
    try:
        receipt = json.loads(output.with_suffix('.failure-workspace.json').read_text(encoding='utf-8'))
        assert receipt['opaqueLinks'] == ['opaque']
        assert receipt['files'] == {}
        assert (outside / 'private.txt').read_text(encoding='utf-8') == 'external observation'
    finally:
        os.rmdir(str(link))
        shutil.rmtree(str(selected))
