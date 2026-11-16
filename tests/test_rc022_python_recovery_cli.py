import json
from pathlib import Path
import subprocess
import sys

import pytest

from apps.cli import main as launcher
from apps.cli import plugin as cli
from apps.cli.args import parse_dsh_args
from dsh.boot import python_plugins as store
from dsh.boot.profile_boot import INSTALL_ANCHOR, run_profile
from dsh.boot.python_plugin_snapshot import retained_installed_package
from test_python_plugin_distribution import profile, close, EXAMPLE, PACKAGE
from test_rc022_python_package_acquire import registry_package
from test_rc022_python_package_backend import start


def retained(directory):
    store.install(str(directory), str(EXAMPLE), INSTALL_ANCHOR, enabled=False)
    with retained_installed_package(str(directory), PACKAGE) as snapshot:
        store.uninstall(str(directory), PACKAGE)
        return snapshot.preserve('injected-restoration-failure')


def test_canonical_recovery_command_without_pnpm_restores_disabled(profile, monkeypatch, capsys):
    _, directory = profile
    recovery = retained(directory)
    invocation = ['dsh', 'plugin', '--profile', 'python-test', 'recover', recovery]
    assert parse_dsh_args(invocation[1:])['args'] == ['recover', recovery]
    monkeypatch.setattr(sys, 'argv', invocation)
    with pytest.raises(SystemExit) as stopped:
        launcher.main()
    assert stopped.value.code == 0
    assert 'disabled; enable after reviewing' in capsys.readouterr().out
    manifest = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
    assert PACKAGE in manifest['dsh']['pythonPlugins'] and PACKAGE not in manifest['dsh']['profile']['bundles']
    assert not Path(recovery).exists()
    store.uninstall(str(directory), PACKAGE)


@pytest.mark.parametrize('arguments', [[], ['one', 'two']])
def test_recovery_argument_errors_do_not_fall_back_to_pnpm(profile, arguments):
    _, directory = profile
    before = (directory / 'package.json').read_bytes()
    with pytest.raises(ValueError, match='use recover'):
        cli.run_plugin('python-test', ['recover'] + arguments)
    assert (directory / 'package.json').read_bytes() == before


@pytest.mark.asyncio
async def test_recovery_cli_refuses_running_profile_and_preserves_its_only_copy(profile, monkeypatch, capsys):
    home, directory = profile
    recovery = retained(directory)
    before = (directory / 'package.json').read_bytes()
    host = await run_profile(dict(profile='python-test', dshHome=str(home), args=[], waitForExit=False))
    try:
        monkeypatch.setattr(sys, 'argv', ['dsh', 'plugin', '--profile', 'python-test', 'recover', recovery])
        with pytest.raises(SystemExit) as stopped:
            launcher.main()
        assert stopped.value.code == 1 and capsys.readouterr().err
        assert (directory / 'package.json').read_bytes() == before
        assert (Path(recovery) / 'package').is_dir() and (Path(recovery) / 'recovery.json').is_file()
    finally:
        await close(host)
    assert cli.run_plugin('python-test', ['recover', recovery]) == 0
    assert not Path(recovery).exists()
    store.uninstall(str(directory), PACKAGE)


@pytest.mark.asyncio
async def test_backend_failure_command_with_spaces_runs_actual_cli(profile, registry_package, monkeypatch):
    home, directory = profile
    spaced = home.with_name('home with spaces')
    assert home.resolve().parent == spaced.resolve().parent
    home.rename(spaced)
    home, directory = spaced, spaced / 'profiles/python-test'
    monkeypatch.setenv('DSH_HOME', str(home))
    store.install(str(directory), str(EXAMPLE), INSTALL_ANCHOR, enabled=False)
    host = await start(home, registry_package)
    try:
        async def interrupted():
            with host['ctx'].pythonProfileLease.exclusive_window():
                store.uninstall(str(directory), PACKAGE, lease=host['ctx'].pythonProfileLease)
            return dict(restore=dict(application='failed', error=dict(code='operation-error', diagnostic='injected restore failure')))
        result = await host['ctx'].profilePackages.update(PACKAGE, interrupted, 0)
        command = result['recovery']['command']
        assert command[:5] == ['dsh', 'plugin', '--profile', 'python-test', 'recover']
        assert 'home with spaces' in command[-1]
        assert subprocess.list2cmdline(command) in result['restore']['error']['diagnostic']
    finally:
        await close(host)
    monkeypatch.setattr(sys, 'argv', command)
    with pytest.raises(SystemExit) as stopped:
        launcher.main()
    assert stopped.value.code == 0 and not Path(command[-1]).exists()
    store.uninstall(str(directory), PACKAGE)
