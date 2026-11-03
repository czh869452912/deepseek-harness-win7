"""Run the actual Electron22 Node16 updater adapter and Source coordinator."""
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_actual_node16_signed_update_and_coordinator(tmp_path):
    electron = ROOT / '.goose/tools/electron-22.3.27-win32-x64/runtime/electron.exe'
    result = subprocess.run([str(electron), str(ROOT / 'scripts/oracles/desktop_updates_current.cjs')],
        env=dict(os.environ, ELECTRON_RUN_AS_NODE='1'),
        capture_output=True, timeout=60)
    (tmp_path / 'stdout.json').write_bytes(result.stdout)
    (tmp_path / 'stderr.log').write_bytes(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'qualified'
    assert len(report['checks']) == 41
    assert {'monotonic-distribution-revision', 'distribution-revision-before-next-upstream',
            'reject-invalid-distribution-revision', 'signed-distribution-revision-release'}.issubset(report['checks'])
    assert {'reject-invalid-private-CA-configuration', 'actual-explicit-private-CA-through-HTTPS-redirect'}.issubset(report['checks'])
    assert report['installationExecuted'] is False
