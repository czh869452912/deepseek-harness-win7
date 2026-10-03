import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_actual_original_mcp_disposal_source_native_queue_and_factory_ownership(tmp_path):
    output = tmp_path / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/mcp_disposal_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
    assert completed.returncode == 0, (completed.stdout + completed.stderr).decode('utf-8', 'replace')
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'passed' and report['cases'] == 7
