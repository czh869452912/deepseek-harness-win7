"""Current qualification rejects stale candidates and partial packaged evidence."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from scripts import current_release_gate as gate
from scripts import verify_release


def test_browser_generated_diagnostics_preserved_without_masking_runtime_changes(tmp_path):
    runtime = tmp_path / 'browser'; runtime.mkdir()
    browser = runtime / 'chrome.exe'; browser.write_bytes(b'pinned browser')
    library = runtime / 'runtime.dll'; library.write_bytes(b'pinned library')
    nested = runtime / 'nested'; nested.mkdir()
    nested_log = nested / 'debug.log'; nested_log.write_bytes(b'input')
    output = tmp_path / 'observations'; output.mkdir()
    before = gate.browser_support_identity([runtime], [browser])
    log = runtime / 'debug.log'; log.write_bytes(b'GPU diagnostic\r\n')
    assert gate.browser_support_identity([runtime], [browser]) == before
    gate.capture_browser_diagnostics([browser], output, 'after')
    assert (output / 'browser-0-after-debug.log').read_bytes() == log.read_bytes()
    receipt = json.loads((output / 'browser-diagnostics-after.json').read_text(encoding='utf-8'))
    assert receipt[0]['sha256'] == gate.lanes.digest(log)
    for path in [browser, library, nested_log]:
        original = path.read_bytes(); path.write_bytes(b'changed')
        assert gate.browser_support_identity([runtime], [browser]) != before
        path.write_bytes(original)
    log.unlink()
    assert gate.browser_support_identity([runtime], [browser]) == before


def test_browser_diagnostic_link_cannot_escape_input_validation(tmp_path):
    runtime = tmp_path / 'browser'; runtime.mkdir()
    browser = runtime / 'chrome.exe'; browser.write_bytes(b'browser')
    target = runtime / 'real.log'; target.write_bytes(b'data')
    link = runtime / 'debug.log'; link.symlink_to(target)
    try:
        with pytest.raises(ValueError, match='Linked browser diagnostic'):
            gate.browser_support_identity([runtime], [browser])
        with pytest.raises(ValueError, match='Linked browser diagnostic'):
            gate.capture_browser_diagnostics([browser], tmp_path, 'after')
    finally:
        link.unlink()


def test_current_cli_routes_to_current_qualification(tmp_path, monkeypatch):
    received = []
    def verify(args, output):
        received.append((args.current, args.python32, args.site_packages32, args.source_test_node))
        return dict(result='passed', publishable=False)
    monkeypatch.setattr(gate, 'verify', verify)
    assert verify_release.main(['--python32', 'base32', '--site-packages32', 'deps32',
                                '--source-test-node', 'source-test-node.exe',
                                '--output-dir', str(tmp_path)]) == 0
    assert received == [(True, Path('base32'), Path('deps32'), Path('source-test-node.exe'))]


@pytest.mark.parametrize('damage', ['none', 'changed-archive'])
def test_current_gate_smokes_and_extracts_the_same_fresh_archive(tmp_path, monkeypatch, damage):
    from scripts import browser108_gate
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    browsers = [tmp_path / name for name in ('node.exe', 'browser.exe', 'browser108.exe')]
    for path in browsers:
        path.write_bytes(b'actual selected input')
    node, browser, browser108 = browsers
    args = NS(node=node, browser=browser, browser108=browser108, office_runtime=tmp_path / 'office',
              prepare=False, allow_dirty=False, regression_timeout=None)
    output = tmp_path / 'output'; output.mkdir()
    selected = dict(product_commit='candidate', worktree_dirty=False)
    monkeypatch.setattr(browser108_gate, 'validate_input', lambda path: {})
    monkeypatch.setattr(gate.retained, 'release_environment', lambda path: {'PATH': ''})
    monkeypatch.setattr(gate, 'runtime_inputs', lambda args: {name: (tmp_path, tmp_path) for name in ('x64', 'x86')})
    monkeypatch.setattr(gate, 'desktop_tools', lambda args: {})
    monkeypatch.setattr(gate, 'candidate', lambda *args: selected)
    def freeze(*args):
        assert args[1] == node
        assert args[-1] == tmp_path / 'source-test-node.exe'
        return dict(checkout={})
    monkeypatch.setattr(gate, 'freeze', freeze)
    monkeypatch.setattr(gate.lanes, 'load_plan', lambda: {})
    monkeypatch.setattr(gate.lanes, 'source_test_runtime', lambda *args: tmp_path / 'source-test-node.exe')
    plan = tmp_path / 'plan.json'; plan.write_bytes(b'fixed plan')
    monkeypatch.setattr(gate.lanes, 'PLAN', plan)
    events, archives = [], {}

    def build(architecture, *args):
        events.append('build-' + architecture)
        folder = output / ('build-' + architecture); folder.mkdir()
        product = folder / 'dsh-win7-portable'; product.mkdir()
        (product / 'python.exe').write_bytes(architecture.encode())
        archive = folder / ('dsh-win7-portable-v' + gate.retained.PORTABLE_VERSION +
                            ('-x86' if architecture == 'x86' else '') + '.zip')
        archive.write_bytes(architecture.encode())
        archives[architecture] = archive
        return folder, dict(path=str(archive), sha256=gate.lanes.digest(archive))

    def regression(python, destination, environment, **kwargs):
        events.append('regression')
        assert environment['DSH_TEST_X86_PYTHON'] == str(tmp_path / 'python.exe')
        product = Path(environment['DSH_TEST_PORTABLE_ROOT'])
        assert product == output / 'build-x64/dsh-win7-portable'
        assert (product / 'python.exe').read_bytes() == b'x64'
        assert archives['x64'].read_bytes() == b'x64'
        if damage == 'changed-archive': archives['x64'].write_bytes(b'foreign archive')

    def qualify(args):
        events.append('extracted-' + args.architecture)
        assert args.archive == archives[args.architecture]
        assert args.expected_commit == 'candidate'
        return dict(status='passed', inputs_unchanged=True)

    monkeypatch.setattr(gate, 'build_archive', build)
    monkeypatch.setattr(gate.retained, 'run_python_regression', regression)
    monkeypatch.setattr(gate.retained, 'validate_regression', lambda path: {})
    def source_lane(*args):
        assert args[2] == tmp_path / 'source-test-node.exe'
        return []
    def paired_lane(*args):
        assert args[2] == node
        return []
    monkeypatch.setattr(gate.lanes, 'source_lane', source_lane)
    monkeypatch.setattr(gate.lanes, 'paired_lane', paired_lane)
    monkeypatch.setattr(gate.portable, 'qualify', qualify)
    monkeypatch.setattr(gate, 'desktop_lane', lambda *args: dict(status='passed'))
    monkeypatch.setattr(gate.lanes, 'remove_owned', lambda path: 0)
    if damage == 'changed-archive':
        with pytest.raises(ValueError, match='Frozen built archive changed'):
            gate.verify(args, output)
        assert events == ['build-x64', 'regression']
    else:
        result = gate.verify(args, output)
        assert result['result'] == 'passed' and result['inputs_unchanged']
        assert events == ['build-x64', 'regression', 'extracted-x64', 'build-x86', 'extracted-x86']


@pytest.mark.parametrize('damage', ['none', 'changed-original'])
def test_nested_current_regression_retains_exact_preflight_inputs(tmp_path, damage):
    from scripts import process_artifact_retention as retention
    product = tmp_path / 'product'
    output_root = product / '.goose/out'
    output = output_root / 'current'
    output.mkdir(parents=True)
    source = product / 'apps/web/dist/index.html'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'actual frozen frontend')
    checkout = {'apps/web/dist/index.html': gate.lanes.digest(source)}
    regression = gate.prepare_regression(output, dict(checkout=checkout))
    workspace = output_root / 'g-inputs'
    workspace.mkdir()
    mapping = dict(execution_path=str(workspace), retained_path=str(regression / 'pytest-workspace'))
    (regression / 'pytest-workspace-mapping.json').write_text(json.dumps(mapping), encoding='utf-8')
    assert json.loads((regression / 'inputs.json').read_text(encoding='utf-8')) == checkout
    if damage == 'changed-original':
        source.write_bytes(b'changed after freeze')
        with pytest.raises(ValueError, match='differs from frozen'):
            retention.preflight_test_inputs(output_root, workspace, product, str(regression))
    else:
        assert retention.preflight_test_inputs(output_root, workspace, product, str(regression)) == checkout


def test_current_gate_binds_root_installed_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    source, node = tmp_path / 'source', tmp_path / 'toolchain/node.exe'
    roots = [source, node.parent, tmp_path / 'node_modules'] + [
        tmp_path / folder / 'node_modules' for folder in
        ['scripts/oracles', 'scripts/oracles/official', 'scripts/source-runtime']]
    for path in roots:
        path.mkdir(parents=True)
    node.write_bytes(b'node')
    module = tmp_path / 'node_modules/module.js'
    module.write_bytes(b'installed dependency')
    before = gate.installed_node_identity(source, node)
    assert str(module) in before['files']
    module.write_bytes(b'changed dependency')
    assert gate.installed_node_identity(source, node) != before
    module.unlink(); module.parent.rmdir()
    with pytest.raises(FileNotFoundError):
        gate.installed_node_identity(source, node)


@pytest.mark.parametrize('damage', ['none', 'pin', 'dirty'])
def test_reused_prepared_source_is_pinned_and_frozen(tmp_path, monkeypatch, damage):
    import os
    from tests.test_qualification_inputs import directory_link
    monkeypatch.setattr(gate, 'ROOT', tmp_path / 'checkout')
    source, node = gate.ROOT / 'source', gate.ROOT / 'toolchain/node.exe'
    for path in [source, node.parent, gate.ROOT / 'node_modules'] + [
            gate.ROOT / folder / 'node_modules' for folder in
            ['scripts/oracles', 'scripts/oracles/official', 'scripts/source-runtime']]:
        path.mkdir(parents=True)
    prepared = tmp_path / 'prepared'
    (prepared / 'node_modules').mkdir(parents=True)
    module = prepared / 'workspace.js'; module.write_bytes(b'prepared workspace')
    link = source / 'node_modules'; directory_link(link, prepared / 'node_modules')
    monkeypatch.setattr(gate, 'git', lambda *args, **kwargs:
        ('stale' if damage == 'pin' else gate.lanes.TARGET) if args[0] == 'rev-parse'
        else ('modified' if damage == 'dirty' else ''))
    try:
        if damage != 'none':
            with pytest.raises(ValueError, match='unchanged current pin'):
                gate.installed_node_identity(source, node)
        else:
            before = gate.installed_node_identity(source, node)
            assert str(module) in before['files']
            module.write_bytes(b'changed prepared workspace')
            assert gate.installed_node_identity(source, node) != before
    finally:
        if os.name == 'nt': os.rmdir(str(link))
        else: link.unlink()


def test_current_x86_runtime_freezes_separate_approved_dependencies(tmp_path):
    args = NS(python32=tmp_path / 'base', site_packages32=tmp_path / 'approved', site_packages=None)
    value = gate.runtime_inputs(args)
    assert value['x86'] == ((tmp_path / 'base').resolve(), (tmp_path / 'approved').resolve())
    assert value['x86'][1] != value['x86'][0] / 'Lib/site-packages'
    with pytest.raises(ValueError, match='Explicit x86'):
        gate.runtime_inputs(NS(python32=args.python32, site_packages32=None))


def test_current_archives_cannot_substitute_the_other_architecture(tmp_path):
    x64 = tmp_path / ('dsh-win7-portable-v' + gate.retained.PORTABLE_VERSION + '.zip')
    x86 = tmp_path / ('dsh-win7-portable-v' + gate.retained.PORTABLE_VERSION + '-x86.zip')
    x64.write_bytes(b'x64')
    assert gate.archive_path(tmp_path, 'x64') == x64
    with pytest.raises(ValueError, match='missing: x86'):
        gate.archive_path(tmp_path, 'x86')
    x86.write_bytes(b'x86')
    assert gate.archive_path(tmp_path, 'x86') == x86


@pytest.mark.parametrize('damage', ['none', 'candidate', 'dirty', 'partial-pipe', 'installer-bytes',
                                   'browser-rejected', 'browser-error', 'browser-console'])
def test_current_desktop_requires_owned_candidate_and_complete_real_observations(tmp_path, monkeypatch, damage):
    destination = tmp_path / 'desktop-x86'
    result = dict(status='built', portable=dict(product_commit='candidate', worktree_dirty=False),
                  pipePreflight=dict(checks=list(range(9))), artifacts=[])
    observer = dict(status='qualified', errors=[], consoleErrors=[])
    executed = []
    def execute(command, cwd, output, name, environment, timeout):
        executed.append(name)
        if name.startswith('desktop-build'):
            destination.mkdir()
            artifact = destination / 'installer.exe'; artifact.write_bytes(b'actual artifact')
            result['artifacts'] = [dict(path=artifact.name, bytes=artifact.stat().st_size, sha256=gate.lanes.digest(artifact))]
            if damage == 'candidate': result['portable']['product_commit'] = 'stale'
            if damage == 'dirty': result['portable']['worktree_dirty'] = True
            if damage == 'partial-pipe': result['pipePreflight']['checks'].pop()
            if damage == 'installer-bytes': artifact.write_bytes(b'foreign')
            (destination / 'desktop-build.json').write_text(json.dumps(result), encoding='utf-8')
        else:
            folder = destination / 'packaged-browser'; folder.mkdir()
            if damage == 'browser-rejected': observer['status'] = 'rejected'
            if damage == 'browser-error': observer['errors'].append('renderer exception')
            if damage == 'browser-console': observer['consoleErrors'].append('console error')
            (folder / 'report.json').write_text(json.dumps(observer), encoding='utf-8')
    monkeypatch.setattr(gate.lanes, 'execute', execute)
    monkeypatch.setattr(gate.lanes, 'retire_success', lambda *args: dict(removed=[]))
    operation = lambda: gate.desktop_lane('x86', tmp_path / 'portable', tmp_path,
                    dict(x86=Path('electron.zip'), nsis=Path('nsis.zip')), Path('node.exe'), {}, 'candidate')
    if damage == 'none':
        assert operation()['status'] == 'passed'
        assert executed == ['desktop-build-x86', 'desktop-browser-x86']
    else:
        with pytest.raises(ValueError): operation()
        if damage in ['candidate', 'dirty', 'partial-pipe', 'installer-bytes']:
            assert executed == ['desktop-build-x86']
