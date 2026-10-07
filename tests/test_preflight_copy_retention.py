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
    assert result['status'] == 'completed' and result['removed_files'] == 2 * len(retention.PREFLIGHT_DAMAGE_CASES) - 1
    assert variant.read_bytes() == b'failed input variant'
    assert observed.read_text(encoding='utf-8') == '{"source":"preserved"}'
    assert archived.read_bytes() == b'actual preserved candidate'
    assert (product / 'apps/web/dist/index.html').read_bytes() == b'original frontend'
    assert (product / 'dsh/session/bin/icu/dsh_icudt78.dll').read_bytes() == b'original ICU data'
    assert retention.prune_preflight_copies(output_root, output, product) is None
    assert json.loads((output / 'preflight-copies-pruned.json').read_text(encoding='utf-8')) == result


@pytest.mark.parametrize('damage', ['unchanged', 'changed-copy', 'changed-original'])
def test_completed_client_copies_require_both_recorded_hashes(tmp_path, damage):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    name = 'packages/client/connection/lib/client.js'
    original = product / name
    original.parent.mkdir(parents=True)
    original.write_bytes(b'original client')
    frozen = retention.read_json(output / 'inputs.json')
    frozen[name] = retention.digest_file(original)
    (output / 'inputs.json').write_text(json.dumps(frozen), encoding='utf-8')
    folder = workspace / 'test_invalid_input_fails_befor0/checkout'
    copied = folder / name
    copied.parent.mkdir(parents=True)
    copied.write_bytes(b'original client')
    unknown = copied.with_name('server.js')
    unknown.write_bytes(b'unknown process material')
    if damage == 'changed-copy':
        copied.write_bytes(b'changed client evidence')
    if damage == 'changed-original':
        original.write_bytes(b'changed original')
        with pytest.raises(ValueError, match='original differs'):
            retention.prune_preflight_copies(output_root, output, product)
        assert copied.read_bytes() == b'original client'
    else:
        result = retention.prune_preflight_copies(output_root, output, product)
        assert result['removed_files'] == 2 * len(retention.PREFLIGHT_DAMAGE_CASES) + (damage == 'unchanged')
        assert copied.exists() == (damage == 'changed-copy')
    assert unknown.read_bytes() == b'unknown process material'


@pytest.mark.parametrize('generation', ['legacy', 'current'])
def test_completed_preflight_supports_recorded_case_generations(tmp_path, generation):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    if generation == 'legacy':
        tree = ET.parse(output / 'pytest.xml')
        suite = tree.getroot().find('testsuite')
        for case in list(suite)[14:]:
            suite.remove(case)
        suite.set('tests', '14')
        tree.write(str(output / 'pytest.xml'), encoding='utf-8')
    result = retention.prune_preflight_copies(output_root, output, product)
    assert result['status'] == 'completed'
    assert result['removed_files'] == 2 * len(retention.PREFLIGHT_DAMAGE_CASES)


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
        assert len(reports) == 1 and reports[0]['removed_files'] == 2 * len(retention.PREFLIGHT_DAMAGE_CASES)
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
    assert (report if mode == 'output' else report[0])['removed_files'] == 2 * len(retention.PREFLIGHT_DAMAGE_CASES)
    assert (product / 'apps/web/dist/index.html').read_bytes() == b'original frontend'
    assert not (workspace / 'test_invalid_input_fails_befor0/checkout/apps/web/dist/index.html').exists()


def test_finished_case_cleanup_does_not_touch_next_active_case(tmp_path):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    frozen = retention.read_json(output / 'inputs.json')
    folder = workspace / 'test_invalid_input_fails_befor0'
    changed = folder / 'checkout/apps/web/dist/index.html'
    changed.write_bytes(b'damaged frontend evidence')
    unknown = folder / 'checkout/apps/web/dist/unknown.bin'
    unknown.write_bytes(b'unknown evidence')
    result = retention.prune_finished_preflight_folder(output_root, workspace, folder, product, frozen)
    assert result['removed_files'] == 1
    assert changed.read_bytes() == b'damaged frontend evidence'
    assert unknown.read_bytes() == b'unknown evidence'
    assert (workspace / 'test_invalid_input_fails_befor1/checkout/dsh/session/bin/icu/dsh_icudt78.dll').exists()
    assert retention.prune_finished_preflight_folder(output_root, workspace, folder, product, frozen) is None


@pytest.mark.parametrize('damage', ['foreign-workspace', 'nested-case', 'unknown-case', 'changed-original', 'invalid-hash'])
def test_finished_case_cleanup_rejects_owner_and_source_changes(tmp_path, damage):
    product, output_root, output, workspace = completed_fixture(tmp_path)
    folder = workspace / 'test_invalid_input_fails_befor0'
    frozen = retention.read_json(output / 'inputs.json')
    if damage == 'foreign-workspace':
        workspace = tmp_path / 'foreign'
        workspace.mkdir()
    elif damage == 'nested-case':
        workspace = output
    elif damage == 'unknown-case':
        folder = workspace / 'test_other0'
        folder.mkdir()
    elif damage == 'changed-original':
        (product / 'apps/web/dist/index.html').write_bytes(b'changed original')
    else:
        frozen['apps/web/dist/index.html'] = 'untrusted'
    with pytest.raises(ValueError):
        retention.prune_finished_preflight_folder(output_root, workspace, folder, product, frozen)
    assert (output / 'pytest-workspace/test_invalid_input_fails_befor0/checkout/dsh/session/bin/icu/dsh_icudt78.dll').exists()


@pytest.mark.parametrize('damage', ['none', 'execution-owner', 'retained-owner', 'changed-original'])
def test_active_release_preflight_snapshot_requires_frozen_owner(tmp_path, damage):
    product, output_root, output, retained = completed_fixture(tmp_path)
    workspace = output_root / 'g-finished'
    workspace.mkdir()
    mapping = retention.read_json(output / 'pytest-workspace-mapping.json')
    if damage == 'execution-owner':
        mapping['execution_path'] = str(retained)
    elif damage == 'retained-owner':
        mapping['retained_path'] = str(output / 'foreign')
    elif damage == 'changed-original':
        (product / 'apps/web/dist/index.html').write_bytes(b'changed original')
    (output / 'pytest-workspace-mapping.json').write_text(json.dumps(mapping), encoding='utf-8')
    if damage == 'none':
        assert retention.preflight_test_inputs(output_root, workspace, product, str(output)) == retention.read_json(output / 'inputs.json')
    else:
        with pytest.raises(ValueError):
            retention.preflight_test_inputs(output_root, workspace, product, str(output))


@pytest.mark.parametrize('failed', [False, True])
@pytest.mark.parametrize('owned', [False, True])
def test_actual_fixture_prunes_between_tests_and_after_failed_body(tmp_path, failed, owned):
    product = tmp_path / 'product'
    output_root = product / '.goose/out'
    workspace = (output_root if owned else tmp_path / 'foreign') / 't-actual'
    workspace.parent.mkdir(parents=True)
    frontend = product / 'apps/web/dist/index.html'
    frontend.parent.mkdir(parents=True)
    frontend.write_bytes(b'original frontend')
    scripts = product / 'scripts'
    scripts.mkdir()
    (scripts / 'frontend-inputs.json').write_text(json.dumps(dict(files=[dict(
        path='apps/web/dist/index.html', sha256=retention.digest_file(frontend))])), encoding='utf-8')
    icu = product / 'dsh/session/bin/icu'
    icu.mkdir(parents=True)
    (icu / 'icu.json').write_text('{"dll_sha256":{},"license_sha256":{}}', encoding='utf-8')
    provider = Path(__file__).with_name('test_release_preflight.py')
    module = tmp_path / 'test_fixture_consumer.py'
    module.write_text('''import importlib.util
from pathlib import Path
import shutil
import pytest
spec = importlib.util.spec_from_file_location('preflight_provider', %r)
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
provider.ROOT = Path(%r)
prune_finished_preflight_case = provider.prune_finished_preflight_case
first = None
@pytest.mark.parametrize('step', [0, 1])
def test_invalid_input_fails_before_release_replacement(tmp_path, step):
    global first
    if step == 1:
        assert first is not None
        assert (first / 'checkout/apps/web/dist/index.html').exists() is %r
        assert (first / 'checkout/apps/web/dist/damaged.bin').read_bytes() == b'failed variant'
        assert (first / 'observations.json').read_bytes() == b'real observation'
    shutil.copytree(provider.ROOT / 'apps/web/dist', tmp_path / 'checkout/apps/web/dist')
    shutil.copytree(provider.ROOT / 'dsh/session/bin/icu', tmp_path / 'checkout/dsh/session/bin/icu')
    (tmp_path / 'checkout/apps/web/dist/damaged.bin').write_bytes(b'failed variant')
    (tmp_path / 'observations.json').write_bytes(b'real observation')
    if step == 0:
        first = tmp_path
        assert %r, 'intentional failed body'
''' % (str(provider), str(product), not owned, not failed), encoding='utf-8')
    import os
    environment = dict(os.environ)
    environment.pop('DSH_RELEASE_PYTEST_OUTPUT', None)
    environment['PYTHONPATH'] = str(Path(retention.__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, '-m', 'pytest', str(module), '-q', '--basetemp=' + str(workspace),
        '--junitxml=' + str(tmp_path / 'actual.xml')], cwd=str(tmp_path), env=environment, capture_output=True, timeout=60)
    assert result.returncode == (1 if failed else 0), result.stdout + result.stderr
    suite = ET.parse(tmp_path / 'actual.xml').getroot().find('testsuite')
    assert suite.attrib['tests'] == '2' and suite.attrib['errors'] == '0'
    assert suite.attrib['failures'] == ('1' if failed else '0')
    for folder in workspace.iterdir():
        if folder.is_dir() and folder.name.startswith('test_invalid_input_fails_befor'):
            assert (folder / 'checkout/apps/web/dist/index.html').exists() is (not owned)
            assert (folder / 'observations.json').read_bytes() == b'real observation'
            if owned:
                audit = retention.read_json(folder / 'preflight-copies-pruned.json')
                assert audit['status'] == 'completed' and audit['removed_files'] == 2
