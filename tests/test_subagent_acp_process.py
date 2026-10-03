import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_actual_parent_acp_subprocess_child_file_model_chain_and_reap(tmp_path):
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/subagent_acp_journey.py'),
        '--root', str(ROOT), '--workspace', str(tmp_path)], cwd=str(ROOT), capture_output=True, timeout=90)
    assert completed.returncode == 0, completed.stdout.decode('utf-8', 'replace') + completed.stderr.decode('utf-8', 'replace')
    assert completed.stderr == b''
    assert json.loads(completed.stdout)['value'] == {'parentRequests': 2, 'childRequests': 2, 'fileWork': True,
        'childReaped': True, 'parentContextIsolated': True, 'parentClosed': True,
        'scope': 'Actual canonical parent ACP, subprocess ACP child and file/model consumers; local endpoint only.'}
