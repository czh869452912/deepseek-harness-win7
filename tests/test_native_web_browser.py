"""Opt-in real-browser lane; default unit runs require no modern test browser.

Set DSH_TEST_CHROMIUM to a Chromium executable on the development machine.
The oracle drives unchanged frontend artifacts against a Python 3.8.10 profile.
This is not Win7/browser certification or a remote-model journey.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSER = os.environ.get('DSH_TEST_CHROMIUM')


@pytest.mark.skipif(not BROWSER, reason='real browser lane: set DSH_TEST_CHROMIUM')
def test_original_browser_native_host_cordis_lifecycle(tmp_path):
    node = shutil.which('node')
    assert node is not None, 'real browser developer lane requires Node with global WebSocket'
    output = tmp_path / 'native-browser.json'
    result = subprocess.run([node, str(ROOT / 'scripts/native_web_browser_oracle.mjs'),
        '--browser', BROWSER, '--output', str(output)], cwd=str(ROOT),
        capture_output=True, encoding='utf-8', timeout=150)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['passed'] and report['python'] == '3.8.10'
    assert report['target_upstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert report['clientArtifacts'] and '/api/remote.mux' in report['webSockets']
    assert not report['errors'] and not report['requests'] and not report['hostErrors']
