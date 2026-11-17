"""Current extracted qualification must reject stale artifacts and imports."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from scripts import browser108_gate as notice
from scripts import current_portable_gate as gate
from scripts.verify_portable import product_environment


def test_archive_identity_rejects_another_candidate_before_extraction(tmp_path):
    archive = tmp_path / 'portable.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('dsh-win7-portable/build-provenance.json', json.dumps(
            dict(product_commit='candidate', runtime_inputs_sha256='runtime')))
    assert gate.archive_identity(archive, 'candidate', 'runtime')['product_commit'] == 'candidate'
    with pytest.raises(ValueError, match='candidate differs'):
        gate.archive_identity(archive, 'other', 'runtime')
    with pytest.raises(ValueError, match='runtime data manifest differs'):
        gate.archive_identity(archive, 'candidate', 'other')
    assert not (tmp_path / 'dsh-win7-portable').exists()


@pytest.mark.parametrize('damage', ['root', 'python', 'missing', 'import-bytes', 'frozen-bytes'])
def test_extracted_sdk_requires_actual_candidate_module_bytes(tmp_path, damage):
    modules = {}
    for name in ['apps/cli/main.py', 'dsh/session/session_log_deepseek_current.py',
                 'dsh/llm/deepseek_messages_adapter.py']:
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# actual candidate\n', encoding='utf-8')
        modules[name] = gate.digest(path)
    frozen = dict(modules)
    capture = dict(runtime=dict(root=str(tmp_path), python='3.8.10 test', modules=modules))
    gate.extracted_runtime(capture, tmp_path, frozen)
    if damage == 'root': capture['runtime']['root'] = str(tmp_path / 'other')
    if damage == 'python': capture['runtime']['python'] = '3.11.0'
    if damage == 'missing': modules.pop('apps/cli/main.py')
    if damage == 'import-bytes': (tmp_path / 'apps/cli/main.py').write_text('# altered\n', encoding='utf-8')
    if damage == 'frozen-bytes': frozen['apps/cli/main.py'] = '0' * 64
    with pytest.raises(ValueError): gate.extracted_runtime(capture, tmp_path, frozen)


def current_notice(tmp_path):
    path = tmp_path / gate.CURRENT_NOTICE['relative_path']
    path.parent.mkdir(parents=True)
    path.write_text('- id: ui-settings-general\n  name: "@deepseek-ai/dsh-client-ui-settings-general"\n'
                    '  config:\n    welcomeNoticeVersion: 2026-09-28.1\n', encoding='utf-8')
    prior = dict(passed=True, steps=notice.PORTABLE_STEPS, hostExitCode=0,
                 hostErrors='', exceptions=[], consoleErrors=[])
    report = tmp_path / 'browser.json'; report.write_text(json.dumps(prior), encoding='utf-8')
    return notice.prepare_notice_input(tmp_path, report, prior, notice_config=gate.CURRENT_NOTICE), prior


@pytest.mark.parametrize('damage', ['namespace', 'version', 'old-storage', 'duplicate-owner', 'wrong-owner'])
def test_current_notice_proof_is_bound_to_loader_owned_persistence(tmp_path, damage):
    proof, prior = current_notice(tmp_path)
    notice.validate_notice_input(proof, prior, check_files=True, notice_config=gate.CURRENT_NOTICE)
    changed = copy.deepcopy(proof)
    if damage == 'namespace': changed['namespace'] = 'ui-onboarding'
    if damage == 'version': changed['version'] = notice.NOTICE_VERSION
    if damage == 'old-storage': changed['settings']['text'] = 'ui-onboarding:\n  welcomeNoticeVersion: 2026-09-28.1\n'
    if damage == 'duplicate-owner': changed['settings']['text'] *= 2
    if damage == 'wrong-owner': changed['settings']['text'] = changed['settings']['text'].replace('dsh-client-ui-settings-general', 'different-package')
    with pytest.raises(ValueError): notice.validate_notice_input(changed, prior, notice_config=gate.CURRENT_NOTICE)
    with pytest.raises(ValueError): notice.validate_notice_input(proof, prior)


def test_isolated_windows_environment_keeps_private_absolute_user_directories(tmp_path, monkeypatch):
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'real-user'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'real-cache'))
    env = product_environment(tmp_path / 'portable', tmp_path / 'workspace')
    assert Path(env['USERPROFILE']) == tmp_path / 'workspace/user'
    assert Path(env['LOCALAPPDATA']) == tmp_path / 'workspace/user/AppData/Local'
    assert Path(env['APPDATA']) == tmp_path / 'workspace/user/AppData/Roaming'
    result = subprocess.run([sys.executable, '-c',
        'import os;from dsh.office.contracts import _cache_directory;print(_cache_directory())'],
        cwd=str(gate.ROOT), env=env, capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
    cache = Path(result.stdout.strip())
    assert cache.is_absolute() and Path(env['LOCALAPPDATA']) in cache.parents
