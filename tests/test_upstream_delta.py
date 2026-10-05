import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts import upstream_delta as delta


def commit(repository):
    environment = dict(os.environ, GIT_AUTHOR_NAME='Delta test', GIT_AUTHOR_EMAIL='delta@example.invalid',
        GIT_COMMITTER_NAME='Delta test', GIT_COMMITTER_EMAIL='delta@example.invalid')
    for arguments in (['add', '.'], ['commit', '--quiet', '-m', 'fixture']):
        subprocess.run(['git', '-C', str(repository)] + arguments, env=environment, check=True, capture_output=True)
    return delta.revision(repository, 'HEAD')


@pytest.fixture
def history(tmp_path):
    repository = tmp_path / 'reference'
    repository.mkdir()
    subprocess.run(['git', 'init', '--quiet', str(repository)], check=True, capture_output=True)
    manifests = {
        'package.json': {'name': 'root'},
        'packages/provider/package.json': {'name': 'provider'},
        'packages/consumer/package.json': {'name': 'consumer', 'dependencies': {'provider': 'workspace:*'}},
        'packages/app/package.json': {'name': 'app', 'devDependencies': {'consumer': 'workspace:^'}},
    }
    for name, value in manifests.items():
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    original = repository / 'packages/provider/original.txt'
    original.write_text('original content\n' * 20, encoding='utf-8')
    deleted = repository / 'packages/consumer/deleted.txt'
    deleted.write_text('removed', encoding='utf-8')
    base = commit(repository)
    original.rename(repository / 'packages/consumer/renamed.txt')
    deleted.unlink()
    (repository / 'scripts').mkdir()
    (repository / 'scripts/new.py').write_text('print(1)', encoding='utf-8')
    target = commit(repository)
    rows = []
    names = {value['name'] for value in manifests.values()}
    for name, manifest in manifests.items():
        rows.append(dict(path='reference/' + name, owner='reference' if name == 'package.json' else
            'reference/' + str(Path(name).parent).replace('\\', '/'), name=manifest['name'],
            sha256=hashlib.sha256((repository / name).read_bytes()).hexdigest(),
            workspace_dependencies=[dict(name=dependency, kind=kind, version=version)
                for kind in ('dependencies', 'peerDependencies', 'optionalDependencies', 'devDependencies')
                for dependency, version in sorted(manifest.get(kind, {}).items()) if dependency in names]))
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps(dict(target_upstream=target, manifests=rows,
        non_package_surfaces=[dict(path='reference/scripts', owner='tooling')])), encoding='utf-8')
    return repository, inventory, base, target


def test_real_readonly_delta_preserves_checkout_and_maps_both_rename_owners_and_consumers(history):
    repository, inventory, base, target = history
    before, inventory_bytes = delta.source_state(repository), inventory.read_bytes()
    report = delta.observe(repository, inventory, base, target)
    assert delta.source_state(repository) == before
    assert inventory.read_bytes() == inventory_bytes
    rename = next(row for row in report['changes'] if row['status'].startswith('R'))
    assert rename['before'] == 'packages/provider/original.txt'
    assert rename['after'] == 'packages/consumer/renamed.txt'
    assert rename['pinned_package_owners'] == ['reference/packages/provider', 'reference/packages/consumer']
    assert report['package_impact']['transitive'] == ['reference/packages/app']
    assert report['package_impact']['first_dependency_parent']['reference/packages/app'] == 'reference/packages/consumer'
    assert report['non_package_impact'] == [dict(before=None, after='scripts/new.py',
        surfaces=[dict(path='reference/scripts', owner='tooling')])]
    assert report['unmapped_paths'] == []
    assert delta.observe(repository, inventory, target, target)['changes'] == []


def test_nul_parser_preserves_whitespace_unicode_and_both_copy_names():
    rows = delta.parse_changes('R100\0old\tname\0new\n中文\0C75\0copy-before\0copy-after\0A\0added\0D\0removed\0'.encode('utf-8'))
    assert rows == [dict(status='R100', before='old\tname', after='new\n中文'),
        dict(status='C75', before='copy-before', after='copy-after'), dict(status='A', before=None, after='added'),
        dict(status='D', before='removed', after=None)]


@pytest.mark.parametrize('data', [b'M\0name', b'R100\0old\0', b'A\0\0', b'R101\0old\0new\0',
    b'Q\0name\0', b'M\0../outside\0', b'M\0/absolute\0'])
def test_invalid_git_stream_is_refused(data):
    with pytest.raises(ValueError):
        delta.parse_changes(data)


@pytest.mark.parametrize('damage', ['dirty', 'wrong-pin', 'hash', 'dependency', 'name', 'missing', 'duplicate'])
def test_readonly_observer_refuses_changed_or_incomplete_inventory(history, damage):
    repository, inventory, base, target = history
    value = json.loads(inventory.read_text(encoding='utf-8'))
    if damage == 'dirty':
        (repository / 'unknown.txt').write_text('dirty', encoding='utf-8')
    elif damage == 'wrong-pin':
        value['target_upstream'] = base
    elif damage == 'hash':
        value['manifests'][0]['sha256'] = '0' * 64
    elif damage == 'dependency':
        value['manifests'][2]['workspace_dependencies'] = []
    elif damage == 'name':
        value['manifests'][0]['name'] = 'different'
    elif damage == 'missing':
        value['manifests'].pop()
    else:
        value['manifests'].append(value['manifests'][0])
    inventory.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError):
        delta.observe(repository, inventory, base, target)


def test_invalid_revision_cannot_become_a_git_option_or_write(history):
    repository, inventory, base, target = history
    before = delta.source_state(repository)
    for ref in ('', '--output=outside', '--help', 'HEAD\0bad'):
        with pytest.raises(ValueError):
            delta.revision(repository, ref)
    assert delta.source_state(repository) == before


def test_source_drift_during_observation_is_refused(history, monkeypatch):
    repository, inventory, base, target = history
    state = delta.source_state(repository)
    sequence = iter([state, dict(state, head=base)])
    monkeypatch.setattr(delta, 'source_state', lambda repository: next(sequence))
    with pytest.raises(ValueError, match='changed during'):
        delta.observe(repository, inventory, base, target)


def test_report_output_is_exclusive_and_cannot_change_source_git_or_migration(tmp_path):
    for directory in ('reference', 'migration', '.git'):
        path = tmp_path / directory
        path.mkdir()
        with pytest.raises(ValueError, match='cannot change'):
            delta.write_report({}, path / 'report.json', tmp_path)
        assert not list(path.iterdir())
    output = tmp_path / 'delta.json'
    delta.write_report(dict(result='observed'), output, tmp_path)
    prior = output.read_bytes()
    with pytest.raises(FileExistsError):
        delta.write_report(dict(result='different'), output, tmp_path)
    assert output.read_bytes() == prior


def test_actual_pinned_source_parent_delta_is_readonly_and_source_qualified():
    repository = delta.ROOT / 'reference'
    inventory = delta.ROOT / 'migration/modules.json'
    before, original = delta.source_state(repository), inventory.read_bytes()
    report = delta.observe(repository, inventory, '8437bfb9e4b1a54f2546f4b00d8454967002c0ab',
        'cd5ef8148158c3a752a658978873241fdf8e2bbc')
    assert report['source_pin'] == report['target_commit'] == before['head']
    assert len(report['changes']) == 250
    assert all(row['status'] == 'M' and row['after'].endswith('package.json') for row in report['changes'])
    assert len(report['package_impact']['direct']) == 250
    assert len(report['package_impact']['transitive']) == 1
    assert delta.source_state(repository) == before
    assert inventory.read_bytes() == original
