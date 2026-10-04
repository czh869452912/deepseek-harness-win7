import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.subprocess_tree_oracle import validate_observations


def test_actual_original_and_native_physical_windows_tree_lifecycle(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'trees.json'
    result = subprocess.run([sys.executable, '-m', 'scripts.subprocess_tree_oracle',
        '--output', str(output)], cwd=str(root), env=dict(os.environ), capture_output=True, timeout=90)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', 'replace')
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'passed'
    assert report['cases'] == 4
    original = json.loads(output.with_name(output.stem + '.source.json').read_text(encoding='utf-8'))
    native = json.loads(output.with_name(output.stem + '.native.json').read_text(encoding='utf-8'))
    assert validate_observations(original) == validate_observations(native, root)
