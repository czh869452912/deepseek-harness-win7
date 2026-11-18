import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.session_event_trace_oracle import validate_observations, validate_runtime
from evidence_fixtures import read_member


def test_retained_event_trace_against_immutable_old_source(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'event_trace.json'
    source = read_member('RC3-QUALIFICATION-20261018-228CFACC.zip',
                         'full-gate-root.zip!/session-event-trace-paired.source.json')
    validate_observations(source)
    result = subprocess.run([sys.executable, str(root / 'scripts/oracles/session_event_trace_python.py'),
        str(output)], cwd=str(root), env=dict(os.environ), capture_output=True, timeout=120)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')
    report = json.loads(output.read_text(encoding='utf-8'))
    validate_runtime(report)
    assert report['root'] == str(root) and len(source) == 30
    assert report['observations'] == source
