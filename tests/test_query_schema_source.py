import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_source_query_schema_contract(tmp_path):
    output = tmp_path / 'query-schema.json'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/query_schema_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=180)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')
    receipt = json.loads(output.read_text(encoding='utf-8'))
    assert receipt['status'] == 'passed' and receipt['cases'] == 19
