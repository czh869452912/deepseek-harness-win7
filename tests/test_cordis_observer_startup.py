"""Independent native observer processes must not borrow pytest's import path."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.cordis_runner_oracle import classify as classify_runner
from scripts.cordis_retirement_oracle import classify as classify_retirement

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('observer,classify', [
    ('cordis_runner', classify_runner),
    ('cordis_retirement', classify_retirement),
], ids=['runner', 'retirement'])
def test_isolated_observer_executes_complete_source_journeys(tmp_path, observer, classify):
    output = tmp_path / 'observation.json'
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    completed = subprocess.run([
        sys.executable, '-I', '-B', str(ROOT / ('scripts/oracles/' + observer + '_python.py')),
        str(output),
    ], cwd=str(tmp_path), env=environment, capture_output=True, timeout=90)
    (tmp_path / 'stdout.log').write_bytes(completed.stdout)
    (tmp_path / 'stderr.log').write_bytes(completed.stderr)
    assert completed.returncode == 0, completed.stderr.decode('utf-8', errors='replace')
    native = json.loads(output.read_text(encoding='utf-8'))
    fixture = ROOT / ('tests/fixtures/' + observer.replace('_', '-') + '-source-observations.json')
    source = json.loads(fixture.read_text(encoding='utf-8'))['observations']
    assert [row['mode'] for row in native] == [row['mode'] for row in source]
    assert native
    for left, right in zip(source, native):
        assert classify(left, right) != 'different', left['mode']
