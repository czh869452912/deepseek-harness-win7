import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.session_snapshots_oracle import validate_observations


def test_source_session_snapshots_contract(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'snapshots.json'
    result = subprocess.run([sys.executable, str(root / 'scripts/session_snapshots_oracle.py'),
        '--output', str(output)], cwd=str(root), env=dict(os.environ), capture_output=True, timeout=120)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'passed' and report['cases'] == 18
    validate_observations(json.loads(output.with_name('snapshots.source.json').read_text(encoding='utf-8')))
