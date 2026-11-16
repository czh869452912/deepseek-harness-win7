import asyncio
import json
from pathlib import Path
import shutil
import sys

import pytest

from apps.cli import main as launcher
from apps.cli import plugin as cli
from dsh.boot.profile import read_profile_manifest
from dsh.boot.profile_lease import ProfileLease
from test_python_plugin_distribution import profile, boot, close, echo, PACKAGE
from test_rc022_python_package_acquire import registry_package
from test_rc022_python_package_git import repository
from test_rc022_python_package_update import next_version


def invoke(monkeypatch, *args, profile_name='python-test'):
    monkeypatch.setattr(sys, 'argv', ['dsh', 'plugin', '--profile', profile_name] + list(args))
    with pytest.raises(SystemExit) as result:
        launcher.main()
    return result.value.code


def native_environment(monkeypatch, state):
    certificate = Path(__file__).parent / 'fixtures/tls/localhost-cert.pem'
    for name, value in dict(state['env'], PATH='', SSL_CERT_FILE=str(certificate.resolve())).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cli, 'run_pnpm', lambda *args: pytest.fail('native command cannot fall back to pnpm'))


def test_actual_cli_registry_install_upgrade_offline_rollback_and_cold_start(profile, registry_package, monkeypatch):
    home, directory = profile
    native_environment(monkeypatch, registry_package)
    assert invoke(monkeypatch, 'add', PACKAGE + '@0.1.0', '--registry', registry_package['url']) == 0
    first = read_profile_manifest('dsh', str(directory))
    assert first['dependencies'][PACKAGE] == '0.1.0'
    assert first['dsh']['pythonPlugins'][PACKAGE]['acquisition']['kind'] == 'registry-tgz'
    next_version(registry_package)
    assert invoke(monkeypatch, 'upgrade', PACKAGE + '@0.2.0', '--registry=' + registry_package['url']) == 0
    second = read_profile_manifest('dsh', str(directory))
    assert second['dependencies'][PACKAGE] == '0.2.0'
    requests = list(registry_package['requests'])
    assert invoke(monkeypatch, 'rollback', PACKAGE, '0.1.0') == 0
    restored = read_profile_manifest('dsh', str(directory))
    assert restored['dsh']['pythonPlugins'][PACKAGE]['acquisition'] == first['dsh']['pythonPlugins'][PACKAGE]['acquisition']
    assert restored['dependencies'][PACKAGE] == '0.1.0' and registry_package['requests'] == requests
    async def execute():
        host = await boot(home)
        try:
            assert await echo(host['ctx']) == 'Python echo: hello'
        finally:
            await close(host)
    asyncio.run(execute())
    assert invoke(monkeypatch, 'remove', PACKAGE) == 0
    assert not list(directory.rglob('run.json')) and not (directory / '.dsh-python-downloads').exists()


def test_actual_cli_git_retains_commit_identity_through_upgrade_and_offline_rollback(profile, repository, monkeypatch):
    home, directory = profile
    executable = shutil.which('git')
    monkeypatch.setenv('PATH', str(Path(executable).parent))
    monkeypatch.setattr(cli, 'run_pnpm', lambda *args: pytest.fail('Git native command cannot fall back to pnpm'))
    spec = repository['spec'] + '#' + repository['commit'] + '&path:plugin'
    assert invoke(monkeypatch, 'add', spec) == 0
    first = read_profile_manifest('dsh', str(directory))
    descriptor = repository['source'] / 'plugin/package.json'
    value = json.loads(descriptor.read_text(encoding='utf-8'));value['version'] = '0.2.0'
    descriptor.write_text(json.dumps(value), encoding='utf-8')
    repository['git']('add', '.');repository['git']('commit', '-m', 'CLI Git upgrade')
    commit = repository['git']('rev-parse', 'HEAD')
    assert invoke(monkeypatch, 'upgrade', repository['spec'] + '#' + commit + '&path:plugin') == 0
    assert read_profile_manifest('dsh', str(directory))['dependencies'][PACKAGE].endswith(commit + '&path:plugin')
    monkeypatch.setenv('PATH', '')
    assert invoke(monkeypatch, 'rollback', PACKAGE, '0.1.0') == 0
    restored = read_profile_manifest('dsh', str(directory))
    assert restored['dependencies'][PACKAGE] == spec
    assert restored['dsh']['pythonPlugins'][PACKAGE]['acquisition'] == first['dsh']['pythonPlugins'][PACKAGE]['acquisition']
    assert invoke(monkeypatch, 'remove', PACKAGE) == 0
    assert not (directory / '.dsh-python-downloads').exists()


@pytest.mark.parametrize('invalid_abi', [False, True])
def test_actual_cli_initializes_new_profile_only_after_verified_native_registry_transfer(tmp_path, registry_package, monkeypatch, invalid_abi):
    home = tmp_path / 'new home with spaces'
    monkeypatch.setenv('DSH_HOME', str(home))
    native_environment(monkeypatch, registry_package)
    if invalid_abi:
        registry_package['metadata']['dsh'].pop('python')
        registry_package['pack'](registry_package['metadata'])
    code = invoke(monkeypatch, 'add', PACKAGE, '--registry', registry_package['url'], profile_name='custom')
    directory = home / 'profiles/custom'
    assert code == (1 if invalid_abi else 0)
    assert (directory / 'package.json').exists() is not invalid_abi
    assert not (directory / '.dsh-python-downloads').exists() and not list(directory.rglob('run.json'))
    if not invalid_abi:
        assert invoke(monkeypatch, 'remove', PACKAGE, profile_name='custom') == 0


def test_native_registry_cli_refuses_running_profile_before_network(profile, registry_package, monkeypatch):
    _, directory = profile
    native_environment(monkeypatch, registry_package)
    before = (directory / 'package.json').read_bytes()
    with ProfileLease(str(directory)):
        assert invoke(monkeypatch, 'add', PACKAGE, '--registry', registry_package['url']) == 1
    assert registry_package['requests'] == [] and (directory / 'package.json').read_bytes() == before


@pytest.mark.parametrize('args', [
    ['add'], ['add', PACKAGE, '--registry'], ['add', PACKAGE, '--unknown'],
    ['add', PACKAGE, '--registry='], ['add', PACKAGE, '--registry=x', '--registry=y'],
    ['upgrade', PACKAGE],
])
def test_native_cli_invalid_flags_never_fetch_or_fall_back(profile, registry_package, monkeypatch, args):
    _, directory = profile
    native_environment(monkeypatch, registry_package)
    before = (directory / 'package.json').read_bytes()
    if args == ['upgrade', PACKAGE]:
        # This checks the missing-profile boundary instead of making a lookup.
        profile_name = 'missing-profile'
    else:
        profile_name = 'python-test'
    assert invoke(monkeypatch, *args, profile_name=profile_name) == 1
    assert registry_package['requests'] == [] and (directory / 'package.json').read_bytes() == before
