import json
from pathlib import Path

import pytest

from dsh.boot import python_plugins as store
from dsh.boot.profile import init_profile
from dsh.boot.profile_boot import INSTALL_ANCHOR
from dsh.boot.profile_lease import ProfileLease
from dsh.boot.python_package_acquire import acquired_registry_package
from dsh.boot.python_plugin_snapshot import retained_installed_package, InstalledPackageSnapshot, restore_retained_package
from test_python_plugin_distribution import profile, boot, close, echo, EXAMPLE, PACKAGE
from test_rc022_python_package_acquire import registry_package


@pytest.mark.asyncio
async def test_actual_registry_snapshot_restores_exact_record_without_network(profile, registry_package):
    home, directory = profile
    state = registry_package
    with acquired_registry_package(str(directory), PACKAGE, state['url'], state['env']) as candidate:
        store.install(str(directory), candidate.source, INSTALL_ANCHOR, candidate.acquisition)
    before = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
    calls = list(state['requests'])
    with ProfileLease(str(directory)) as lease:
        with retained_installed_package(str(directory), PACKAGE) as snapshot:
            path = Path(snapshot.source)
            assert path.is_dir()
            with lease.exclusive_window():
                store.uninstall(str(directory), PACKAGE, lease=lease)
                store.install(str(directory), snapshot.source, INSTALL_ANCHOR, lease=lease, _snapshot=snapshot)
            assert json.loads((directory / 'package.json').read_text(encoding='utf-8')) == before
            assert state['requests'] == calls
        assert snapshot.closed and not path.exists() and not (directory / '.dsh-python-updates').exists()
    host = await boot(home)
    try:
        assert await echo(host['ctx']) == 'Python echo: hello'
    finally:
        await close(host)
    store.uninstall(str(directory), PACKAGE)


@pytest.mark.parametrize('damage', ['file', 'descriptor'])
def test_changed_snapshot_cannot_publish_any_profile_bytes(profile, damage):
    _, directory = profile
    store.install(str(directory), str(EXAMPLE), INSTALL_ANCHOR)
    with retained_installed_package(str(directory), PACKAGE) as snapshot:
        store.uninstall(str(directory), PACKAGE)
        before = (directory / 'package.json').read_bytes()
        path = Path(snapshot.source)
        if damage == 'file':
            (path / 'README.md').write_text('changed', encoding='utf-8')
        else:
            descriptor = path / 'package.json'
            manifest = json.loads(descriptor.read_text(encoding='utf-8'))
            manifest['version'] = '9.0.0'
            descriptor.write_text(json.dumps(manifest), encoding='utf-8')
        with pytest.raises(ValueError, match='differs'):
            store.install(str(directory), snapshot.source, INSTALL_ANCHOR, _snapshot=snapshot)
        assert (directory / 'package.json').read_bytes() == before
        assert not (directory / 'node_modules' / PACKAGE).exists()
    assert not (directory / '.dsh-python-updates').exists()


def test_snapshot_capability_rejects_expiry_foreign_source_profile_and_duck_type(profile, tmp_path):
    _, directory = profile
    store.install(str(directory), str(EXAMPLE), INSTALL_ANCHOR)
    foreign = tmp_path / 'foreign'
    init_profile(str(foreign), [])
    with retained_installed_package(str(directory), PACKAGE) as snapshot:
        store.uninstall(str(directory), PACKAGE)
        for target, source in ((foreign, snapshot.source), (directory, str(EXAMPLE))):
            before = (target / 'package.json').read_bytes()
            with pytest.raises(RuntimeError, match='another source/profile'):
                store.install(str(target), source, INSTALL_ANCHOR, _snapshot=snapshot)
            assert (target / 'package.json').read_bytes() == before
        with pytest.raises(RuntimeError, match='owned installed snapshot'):
            store.install(str(directory), snapshot.source, INSTALL_ANCHOR, _snapshot=True)
    with pytest.raises(RuntimeError, match='expired'):
        store.install(str(directory), snapshot.source, INSTALL_ANCHOR, _snapshot=snapshot)
    with pytest.raises(RuntimeError, match='verified owning scope'):
        InstalledPackageSnapshot(str(directory), str(EXAMPLE), {}, {}, None)


def test_changed_installed_package_cannot_establish_recovery_provenance(profile):
    _, directory = profile
    store.install(str(directory), str(EXAMPLE), INSTALL_ANCHOR)
    (directory / 'node_modules' / PACKAGE / 'README.md').write_text('changed', encoding='utf-8')
    before = (directory / 'package.json').read_bytes()
    with pytest.raises(ValueError, match='files changed'):
        with retained_installed_package(str(directory), PACKAGE):
            pytest.fail('changed installed bytes became trusted recovery')
    assert (directory / 'package.json').read_bytes() == before
    assert not (directory / '.dsh-python-updates').exists()


@pytest.mark.parametrize('damage', [None, 'owner', 'profile', 'unknown', 'files'])
def test_preserved_recovery_has_owner_receipt_and_cleans_only_after_success(profile, damage):
    _, directory = profile
    store.install(str(directory), str(EXAMPLE), INSTALL_ANCHOR)
    with retained_installed_package(str(directory), PACKAGE) as snapshot:
        store.uninstall(str(directory), PACKAGE)
        recovery = Path(snapshot.preserve('injected-restoration-failure'))
    assert snapshot.closed and recovery.is_dir()
    receipt = recovery / 'recovery.json'
    value = json.loads(receipt.read_text(encoding='utf-8'))
    assert value['owner'] == 'native-package-update' and value['reviewMilestone']
    if damage is not None:
        if damage in ('owner', 'profile'):
            value[damage] = 'foreign'
        if damage == 'unknown':
            (recovery / 'user-data').write_text('preserve', encoding='utf-8')
        if damage == 'files':
            value['record']['files']['README.md'] = '0' * 64
        receipt.write_text(json.dumps(value), encoding='utf-8')
        before = (directory / 'package.json').read_bytes()
        with pytest.raises(ValueError):
            restore_retained_package(str(directory), str(recovery), INSTALL_ANCHOR)
        assert recovery.is_dir() and (directory / 'package.json').read_bytes() == before
    else:
        assert restore_retained_package(str(directory), str(recovery), INSTALL_ANCHOR) == PACKAGE
        assert not recovery.exists() and not (directory / '.dsh-python-updates').exists()
        assert PACKAGE not in json.loads((directory / 'package.json').read_text(encoding='utf-8'))['dsh']['profile']['bundles']
        store.uninstall(str(directory), PACKAGE)
