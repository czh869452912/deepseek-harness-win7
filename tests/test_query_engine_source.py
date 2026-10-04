import json
from pathlib import Path
import subprocess
import sys


def test_actual_original_native_query_engine_boundaries(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'query-engine.json'
    result = subprocess.run([sys.executable, str(root / 'scripts/query_engine_oracle.py'), '--output', str(output)],
                            cwd=str(root), capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr + output.read_bytes()
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'passed' and report['cases'] == 16
