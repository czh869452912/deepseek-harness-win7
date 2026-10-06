import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from scripts import process_artifact_retention as retention


def completed_fixture(tmp_path):
    product = tmp_path / 'product'
    output_root = product / '.goose/out'
    output = output_root / 'candidate'
    workspace = output / 'pytest-workspace'
    workspace.mkdir(parents=True)
    sources = {'apps/web/dist/index.html': b'original frontend',
        'dsh/session/bin/icu/dsh_icudt78.dll': b'original ICU data'}
    frozen = {}
    for name, payload in sources.items():
        original = product / name
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(payload)
        frozen[name] = retention.digest_file(original)
    (output / 'inputs.json').write_text(json.dumps(frozen), encoding='utf-8')
    (output / 'pytest-workspace-mapping.json').write_text(json.dumps(dict(
        execution_path=str(output_root / 'g-finished'), retained_path=str(workspace))), encoding='utf-8')
    suites = ET.Element('testsuites')
    suite = ET.SubElement(suites, 'testsuite', tests=str(len(retention.PREFLIGHT_DAMAGE_CASES)), failures='0', errors='0')
    for index, damage in enumerate(retention.PREFLIGHT_DAMAGE_CASES):
        ET.SubElement(suite, 'testcase', classname='tests.test_release_preflight',
            name='test_invalid_input_fails_before_release_replacement[' + damage + ']')
        folder = workspace / ('test_invalid_input_fails_befor' + str(index)) / 'checkout'
        for name, payload in sources.items():
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    ET.ElementTree(suites).write(str(output / 'pytest.xml'), encoding='utf-8')
    return product, output_root, output, workspace


def test_completed_preflight_prunes_only_unchanged_reconstructible_copies(tmp_path):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    variant = workspace / 'test_invalid_input_fails_befor0/checkout/apps/web/dist/index.html'
    variant.write_bytes(b'failed input variant')
    observed = workspace / 'test_invalid_input_fails_befor0/actual-source.json'
    observed.write_text('{"source":"preserved"}', encoding='utf-8')
    archived = output / 'candidate-portable.zip'
    archived.write_bytes(b'actual preserved candidate')
    result = retention.prune_preflight_copies(output_root, output, product)
    assert result['status'] == 'completed' and result['removed_files'] == 27
    assert variant.read_bytes() == b'failed input variant'
    assert observed.read_text(encoding='utf-8') == '{"source":"preserved"}'
    assert archived.read_bytes() == b'actual preserved candidate'
    assert (product / 'apps/web/dist/index.html').read_bytes() == b'original frontend'
    assert (product / 'dsh/session/bin/icu/dsh_icudt78.dll').read_bytes() == b'original ICU data'
    assert retention.prune_preflight_copies(output_root, output, product) is None
    assert json.loads((output / 'preflight-copies-pruned.json').read_text(encoding='utf-8')) == result


@pytest.mark.parametrize('damage', ['missing-case', 'duplicate-case', 'failed-case', 'skipped-case',
    'unfinished', 'active', 'changed-original', 'external-owner'])
def test_unfinished_unowned_or_changed_preflight_inputs_stay_retained(tmp_path, damage):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    xml = output / 'pytest.xml'
    tree = ET.parse(str(xml))
    suite = tree.getroot().find('testsuite')
    if damage == 'missing-case':
        suite.remove(suite[-1])
        suite.set('tests', str(len(suite)))
    elif damage == 'duplicate-case':
        suite[-1].set('name', suite[0].attrib['name'])
    elif damage == 'failed-case':
        ET.SubElement(suite[0], 'failure', message='actual preflight failure')
    elif damage == 'skipped-case':
        ET.SubElement(suite[0], 'skipped')
    elif damage == 'unfinished':
        suite.set('tests', '999')
    elif damage == 'active':
        (output_root / 'g-finished').mkdir()
    elif damage == 'changed-original':
        (product / 'apps/web/dist/index.html').write_bytes(b'changed original')
    else:
        output_root = tmp_path / 'other'
        output_root.mkdir()
    tree.write(str(xml), encoding='utf-8')
    if damage in ('missing-case', 'duplicate-case', 'failed-case', 'skipped-case'):
        assert retention.prune_preflight_copies(output_root, output, product) is None
    else:
        with pytest.raises(ValueError):
            retention.prune_preflight_copies(output_root, output, product)
    for index in range(len(retention.PREFLIGHT_DAMAGE_CASES)):
        assert (workspace / ('test_invalid_input_fails_befor' + str(index)) / 'checkout/apps/web/dist/index.html').read_bytes() == b'original frontend'
    assert not (output / 'preflight-copies-pruned.json').exists()


@pytest.mark.parametrize('state', ['passed', 'failed', 'running', 'missing'])
def test_previous_preflight_maintenance_requires_completed_release_state(tmp_path, state):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    if state != 'missing':
        (output / 'summary.json').write_text(json.dumps(dict(result=state)), encoding='utf-8')
    reports = retention.prune_previous_preflight_copies(output_root, product)
    target = workspace / 'test_invalid_input_fails_befor0/checkout/apps/web/dist/index.html'
    if state in ('passed', 'failed'):
        assert len(reports) == 1 and reports[0]['removed_files'] == 28
        assert not target.exists()
    else:
        assert reports == [] and target.exists()


def test_preflight_copy_changed_after_classification_is_preserved(tmp_path, monkeypatch):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    target = workspace / 'test_invalid_input_fails_befor0/checkout/apps/web/dist/index.html'
    original_digest = retention.digest_file
    observed = []
    def change_before_unlink(path):
        if str(path) == str(target):
            observed.append(path)
            if len(observed) == 2:
                target.write_bytes(b'changed after classification')
        return original_digest(path)
    monkeypatch.setattr(retention, 'digest_file', change_before_unlink)
    with pytest.raises(RuntimeError, match='changed before cleanup'):
        retention.prune_preflight_copies(output_root, output, product)
    assert target.read_bytes() == b'changed after classification'
    audit = json.loads((output / 'preflight-copies-pruned.json').read_text(encoding='utf-8'))
    assert audit['status'] == 'failed' and audit['removed_files'] == 0
    assert (product / 'apps/web/dist/index.html').read_bytes() == b'original frontend'


@pytest.mark.parametrize('damage', ['wrong-type', 'aliased-input'])
def test_malformed_frozen_preflight_manifest_never_deletes_copies(tmp_path, damage):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    path = output / 'inputs.json'
    frozen = json.loads(path.read_text(encoding='utf-8'))
    if damage == 'wrong-type':
        frozen = []
    else:
        frozen['apps/web/dist/./index.html'] = frozen.pop('apps/web/dist/index.html')
    path.write_text(json.dumps(frozen), encoding='utf-8')
    with pytest.raises(ValueError):
        retention.prune_preflight_copies(output_root, output, product)
    assert (workspace / 'test_invalid_input_fails_befor0/checkout/apps/web/dist/index.html').read_bytes() == b'original frontend'


@pytest.mark.parametrize('mode', ['previous', 'output'])
def test_actual_maintenance_cli_prunes_completed_preflight_copies(tmp_path, mode):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    (output / 'summary.json').write_text('{"result":"passed"}', encoding='utf-8')
    script = product / 'scripts/process_artifact_retention.py'
    script.parent.mkdir()
    script.write_bytes(Path(retention.__file__).read_bytes())
    command = [sys.executable, str(script)] + (['--output', str(output)] if mode == 'output' else [])
    completed = subprocess.run(command, capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)['preflight_copies']
    assert (report if mode == 'output' else report[0])['removed_files'] == 28
    assert (product / 'apps/web/dist/index.html').read_bytes() == b'original frontend'
    assert not (workspace / 'test_invalid_input_fails_befor0/checkout/apps/web/dist/index.html').exists()
