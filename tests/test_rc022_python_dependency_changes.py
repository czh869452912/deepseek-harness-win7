"""Prepare immutable library graphs before live native package transactions."""
import importlib
from pathlib import Path
import sys

import pytest

from dsh.boot import python_plugin_dependencies as dependencies
from dsh.boot import python_plugins as store
from dsh.boot.profile import init_profile
from dsh.boot.profile_boot import INSTALL_ANCHOR, run_profile
from dsh.boot.python_package import import_package
from test_python_plugin_dependencies import project
from test_python_plugin_distribution import profile, close, PACKAGE


def add(directory, lease, runtime, source):
    prepared = runtime.prepare_change(str(source))
    try:
        with lease.exclusive_window():
            name = store.install(str(directory), str(source), INSTALL_ANCHOR, lease=lease, enabled=False)
            runtime.commit_change(prepared)
        return name
    finally:
        prepared.close()


def remove(directory, lease, runtime, name):
    prepared = runtime.prepare_change(removing=name)
    try:
        with lease.exclusive_window():
            store.uninstall(str(directory), name, lease=lease)
            runtime.commit_change(prepared)
    finally:
        prepared.close()


@pytest.mark.asyncio
async def test_live_add_shared_library_remove_and_shutdown(profile, tmp_path):
    home, directory = profile
    before = sys.path[:]
    host = await run_profile(dict(profile='python-test', dshHome=str(home), args=[], waitForExit=False))
    lease, runtime = host['ctx'].get('pythonProfileLease'), host['ctx'].get('pythonDependencies')
    paths = []
    try:
        first = project(tmp_path)
        add(directory, lease, runtime, first)
        import_package(str(directory / 'node_modules' / PACKAGE))
        helper = importlib.import_module('test_helper')
        assert helper.format('one') == 'locked-sub:one:1'
        paths = [row['temporary'].name for row in dependencies._POOL.values()]
        second_name = '@example/second'
        add(directory, lease, runtime, project(tmp_path, name=second_name))
        import_package(str(directory / 'node_modules' / second_name))
        assert importlib.import_module('test_helper') is helper
        assert helper.format('two') == 'locked-sub:two:2'
        remove(directory, lease, runtime, PACKAGE)
        assert helper.format('three') == 'locked-sub:three:3'
        assert importlib.import_module('test_helper.late').VALUE == 'late-from-copy'
        assert all(Path(path).is_dir() for path in paths)
        remove(directory, lease, runtime, second_name)
        assert not dependencies._POOL and not dependencies._PACKAGES
        assert not any(Path(path).exists() for path in paths)
        assert 'test_helper' not in sys.modules and 'test_helper.late' not in sys.modules
        assert not lease.exclusive and not runtime.closed
    finally:
        await close(host)
    assert lease.stream is None and runtime.closed and sys.path == before


def test_abandoned_preparation_removes_only_its_new_copies(profile, tmp_path):
    _, directory = profile
    runtime = dependencies.PythonDependencyLease(str(directory))
    before = sys.path[:]
    prepared = runtime.prepare_change(str(project(tmp_path)))
    paths = [row['temporary'].name for row in dependencies._POOL.values()]
    assert len(paths) == 2 and all(Path(path).is_dir() for path in paths)
    assert not (directory / 'node_modules' / PACKAGE).exists()
    prepared.close()
    assert not runtime.closed and not dependencies._POOL and not dependencies._PACKAGES
    assert not any(Path(path).exists() for path in paths) and sys.path == before
    runtime.close()


@pytest.mark.asyncio
async def test_conflicting_active_profile_keeps_both_runtime_and_profile_bytes(profile, tmp_path):
    home, directory = profile
    store.install(str(directory), str(project(tmp_path)), INSTALL_ANCHOR)
    host = await run_profile(dict(profile='python-test', dshHome=str(home), args=[], waitForExit=False))
    other = tmp_path / 'other'
    init_profile(str(other), [])
    runtime = dependencies.PythonDependencyLease(str(other))
    before = (other / 'package.json').read_bytes()
    helper = importlib.import_module('test_helper')
    paths = sys.path[:]
    try:
        with pytest.raises(RuntimeError, match='active profile'):
            runtime.prepare_change(str(project(tmp_path, version='2.0.0', library_version='2.0.0', text='new')))
        assert sys.path == paths and importlib.import_module('test_helper') is helper
        assert helper.format('kept') == 'locked-sub:kept:1'
        assert (other / 'package.json').read_bytes() == before and not runtime.closed
    finally:
        runtime.close()
        await close(host)
    assert not dependencies._POOL and not dependencies._PACKAGES


def test_invalid_lease_transfer_is_refused(profile, tmp_path):
    _, directory = profile
    runtime = dependencies.PythonDependencyLease(str(directory))
    other = tmp_path / 'other'
    init_profile(str(other), [])
    foreign = dependencies.PythonDependencyLease(str(other))
    prepared = runtime.prepare_change()
    try:
        for value in (runtime, foreign, None, True):
            with pytest.raises(RuntimeError, match='prepared dependency lease'):
                runtime.commit_change(value)
        assert not runtime.closed and not prepared.closed and not foreign.closed
        runtime.commit_change(prepared)
        assert prepared.closed and not runtime.closed
        with pytest.raises(RuntimeError, match='prepared dependency lease'):
            runtime.commit_change(prepared)
    finally:
        runtime.close()
        foreign.close()
        prepared.close()
    with pytest.raises(RuntimeError, match='closed'):
        runtime.prepare_change()
