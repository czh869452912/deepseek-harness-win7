import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_actual_redirect_fixture_never_sends_empty_response_body(tmp_path):
    output = tmp_path / 'redirect-observations.json'
    code = '''import runpy, socketserver, sys
original = socketserver._SocketWriter.write
def checked_write(writer, data):
    if not data:
        raise AssertionError('Unexpected zero-byte response write after headers')
    return original(writer, data)
socketserver._SocketWriter.write = checked_write
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
    completed = subprocess.run([sys.executable, '-I', '-c', code,
        str(ROOT / 'scripts/oracles/http_redirect_python.py'), '--root', str(ROOT), '--output', str(output)],
        cwd=str(ROOT), capture_output=True, timeout=45)
    assert completed.returncode == 0 and not completed.stderr, completed.stderr
    report = json.loads(output.read_text(encoding='utf-8'))
    assert len(report['rows']) == 29
    abort = next(row for row in report['rows'] if row['name'] == 'raw-abort-before-follow')
    assert len(abort['requests']) == 1 and abort['error']['code'] == 'ABORTED'
    stalled = next(row for row in report['rows'] if row['name'] == 'raw-stalled-redirect-body')
    assert len(stalled['requests']) == 2 and stalled['status'] == 200 and 'ok' in stalled['text']
