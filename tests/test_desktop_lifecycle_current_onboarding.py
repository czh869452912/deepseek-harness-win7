import json
import sys

import pytest

from scripts import verify_desktop_lifecycle as lifecycle


@pytest.mark.parametrize('current', [False, True])
def test_cli_onboarding_selection_reaches_both_real_observer_invocations(tmp_path, monkeypatch, current):
    installer = tmp_path / 'installer.exe'; installer.write_bytes(b'fixture')
    output = tmp_path / 'observations'
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'lanes': [{'id': 'x64-aio', 'installer': str(installer)}]}), encoding='utf-8')
    commands = []

    class Administrator:
        def __init__(self, command, **kwargs):
            kwargs['stdout'].close(); kwargs['stderr'].close()
            lane = output / 'x64-aio'; lane.mkdir()
            (lane / 'installed.json').write_text(json.dumps({'executable': str(installer)}), encoding='utf-8')
            (output / 'administrator-report.json').write_text(json.dumps({'status': 'passed', 'restored': True}), encoding='utf-8')

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    def observer(command, **kwargs):
        commands.append(command)
        return type('Result', (), {'returncode': 0})()

    monkeypatch.setattr(lifecycle.subprocess, 'Popen', Administrator)
    monkeypatch.setattr(lifecycle.subprocess, 'run', observer)
    argv = ['verify_desktop_lifecycle.py', '--plan', str(plan), '--node', str(tmp_path / 'node.exe'), '--output', str(output)]
    if current:
        argv.append('--current-onboarding')
    monkeypatch.setattr(sys, 'argv', argv)
    assert lifecycle.main() == 0
    assert len(commands) == 2
    assert ['--seed', 'plaintext'] == commands[0][-2 - (2 if current else 0):][:2]
    assert '--home' in commands[1]
    assert all(('--current-onboarding' in command) == current for command in commands)
    if current:
        assert all(command[-2:] == ['--current-onboarding', 'true'] for command in commands)
