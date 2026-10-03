import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_actual_acp_process_owns_stdio_http_session_tools_and_model_consumers(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/acp_mcp_journey.py'),
        '--root', str(ROOT), '--workspace', str(tmp_path)], capture_output=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0 and not result.stderr, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['result'] == 'passed'
    assert report['value'] == {'stdioProcesses': 3, 'stdioCalls': 3, 'stdioReaped': True,
        'httpCalls': 1, 'httpClosed': True, 'acpClosed': True, 'modelRequests': 8,
        'scope': 'Actual canonical ACP process, stdio/HTTP consumers and same-session resume; no external endpoint.'}
