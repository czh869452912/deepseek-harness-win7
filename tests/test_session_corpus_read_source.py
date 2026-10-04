import json
from pathlib import Path
import subprocess
import sys

from scripts.session_corpus_read_oracle import validate_observations, validate_runtime


def test_actual_original_and_native_corpus_load_and_title_batch_signal_drain_and_source_ownership(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'read.json'
    result = subprocess.run([sys.executable, str(root / 'scripts/session_corpus_read_oracle.py'),
        '--output', str(output)], cwd=str(root), capture_output=True, timeout=90)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', 'replace')
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'passed' and report['cases'] == 19
    source = json.loads(output.with_name(output.stem + '.source.json').read_text(encoding='utf-8'))
    native = json.loads(output.with_name(output.stem + '.native.json').read_text(encoding='utf-8'))
    validate_observations(source)
    validate_runtime(native)
    assert source == native['observations']
