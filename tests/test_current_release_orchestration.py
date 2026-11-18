"""Current qualification rejects stale candidates and partial packaged evidence."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from scripts import current_release_gate as gate
from scripts import verify_release


def test_current_cli_routes_to_current_qualification(tmp_path, monkeypatch):
    received = []
    def verify(args, output):
        received.append((args.current, args.python32, args.site_packages32))
        return dict(result='passed', publishable=False)
    monkeypatch.setattr(gate, 'verify', verify)
    assert verify_release.main(['--python32', 'base32', '--site-packages32', 'deps32',
                                '--output-dir', str(tmp_path)]) == 0
    assert received == [(True, Path('base32'), Path('deps32'))]


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
