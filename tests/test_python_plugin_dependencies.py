"""Locked libraries through actual canonical boot, sharing and version recovery."""
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types

import pytest

from apps.cli import plugin as cli
from dsh.boot import python_plugin_dependencies as dependencies
from dsh.boot.python_package import import_package, validate_sources
from dsh.boot.profile import init_profile
from dsh.boot.profile_boot import run_profile
from test_python_plugin_distribution import profile, close, echo, EXAMPLE, PACKAGE
from test_python_plugin_versions import zip_source, installed


def project(tmp_path, name=PACKAGE, version='1.0.0', library_version='1.0.0', text='locked'):
    source = tmp_path / ('source-' + name.split('/')[-1] + '-' + version)
    shutil.copytree(str(EXAMPLE), str(source), ignore=shutil.ignore_patterns('__pycache__'))
    descriptor = source / 'package.json'
    manifest = json.loads(descriptor.read_text(encoding='utf-8'))
    manifest.update(name=name, version=version)
    manifest['dsh']['python']['dependencies'] = ['test-helper==' + library_version]
    (source / 'python/echo/formatting.py').write_text('import test_helper\ndef format_echo(text):\n    return test_helper.format(text)\n', encoding='utf-8')
    library_rows = []
    for distribution, module, requires, code in (
        ('test-helper', 'test_helper', ['test-leaf==1.0.0'], 'import test_leaf\nfrom . import sub\ncount = 0\ndef format(text):\n    global count\n    count += 1\n    return test_leaf.PREFIX + sub.VALUE + ":" + text + ":" + str(count)\n'),
        ('test-leaf', 'test_leaf', [], 'PREFIX = ' + repr(text) + '\n'),
    ):
        root = source / 'vendor' / distribution
        package = root / module
        package.mkdir(parents=True)
        (package / '__init__.py').write_text(code, encoding='utf-8')
        if module == 'test_helper':
            (package / 'sub.py').write_text('VALUE = "-sub"\n', encoding='utf-8')
            (package / 'late.py').write_text('VALUE = "late-from-copy"\n', encoding='utf-8')
        (root / 'LICENSE').write_text('Private fixture library license', encoding='utf-8')
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        library_rows.append(dict(name=distribution, version=library_version if module == 'test_helper' else '1.0.0',
            sourceRoot='vendor/' + distribution, imports=[module], requires=requires, files=files, origin='private-test-files'))
    manifest['dsh']['pythonDependencies'] = dict(formatVersion=1, python=[3, 8, 10], abi='none', platform='any', packages=library_rows)
    manifest['dsh']['release'] = dict(formatVersion=1, files=sorted(p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()))
    descriptor.write_text(json.dumps(manifest), encoding='utf-8')
    return source


def change(source, function):
    path = source / 'package.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    function(manifest)
    path.write_text(json.dumps(manifest), encoding='utf-8')


async def boot_profile(home, name='python-test'):
    return await run_profile(dict(profile=name, dshHome=str(home), args=[], waitForExit=False))


async def format_call(result, text):
    return await echo(result['ctx'], text)


@pytest.mark.asyncio
@pytest.mark.parametrize('container', ['directory', 'zip'])
async def test_complete_offline_closure_boot_restart_upgrade_and_rollback(profile, tmp_path, container):
    home, directory = profile
    before = sys.path[:]
    source = project(tmp_path)
    if container == 'zip':
        archive = tmp_path / 'author.zip'
        assert cli.run_plugin('python-test', ['pack', str(source), str(archive)]) == 0
        source = archive
    assert cli.run_plugin('python-test', ['add', str(source)]) == 0
    with pytest.raises(RuntimeError, match='runtime lease'):
        import_package(str(installed(directory)))
    for _ in range(2):
        result = await boot_profile(home)
        try:
            assert await format_call(result, 'one') == 'locked-sub:one:1'
            assert await format_call(result, 'two') == 'locked-sub:two:2'
            module = importlib.import_module('test_helper')
            assert 'dsh-python-dependencies-' in module.__file__
            assert (Path(module.__file__).parent.parent / 'LICENSE').is_file()
        finally:
            await close(result)
        assert sys.path == before and 'test_helper' not in sys.modules
        assert not dependencies._POOL and not dependencies._PACKAGES
    newer = project(tmp_path, version='2.0.0', library_version='2.0.0', text='upgraded')
    assert cli.run_plugin('python-test', ['upgrade', str(newer)]) == 0
    result = await boot_profile(home)
    try:
        assert await format_call(result, 'v2') == 'upgraded-sub:v2:1'
    finally:
        await close(result)
    assert cli.run_plugin('python-test', ['rollback', PACKAGE, '1.0.0']) == 0
    result = await boot_profile(home)
    try:
        assert await format_call(result, 'old') == 'locked-sub:old:1'
    finally:
        await close(result)
    assert cli.run_plugin('python-test', ['remove', PACKAGE]) == 0
    assert sys.path == before and not dependencies._POOL and not dependencies._PACKAGES


def second_profile(home, name):
    directory = home / 'profiles' / name
    init_profile(str(directory), [], 'startup')
    (directory / 'cordis.patch.yml').write_text(
        "- insert:\n    - id: system-prompt\n      name: '@deepseek-ai/dsh-system-prompt'\n"
        "    - id: tools\n      name: '@deepseek-ai/dsh-tools'\n", encoding='utf-8')
    return directory


@pytest.mark.asyncio
async def test_compatible_profiles_share_copied_libraries_after_source_owner_removal(profile, tmp_path):
    home, directory = profile
    before = sys.path[:]
    second_profile(home, 'second')
    source = project(tmp_path)
    cli.run_plugin('python-test', ['add', str(source)])
    cli.run_plugin('second', ['add', str(source)])
    first = await boot_profile(home)
    second = None
    try:
        assert await format_call(first, 'first') == 'locked-sub:first:1'
        second = await boot_profile(home, 'second')
        assert await format_call(second, 'second') == 'locked-sub:second:2'
        copied = Path(importlib.import_module('test_helper').__file__).parent
        await close(first)
        first = None
        cli.run_plugin('python-test', ['remove', PACKAGE])
        assert not installed(directory).exists()
        assert importlib.import_module('test_helper.late').VALUE == 'late-from-copy'
        assert copied.is_dir()
        assert await format_call(second, 'survives') == 'locked-sub:survives:3'
    finally:
        if first is not None:
            await close(first)
        if second is not None:
            await close(second)
    assert not copied.exists()
    assert not any(str(path).startswith(str(copied.parent)) for path in sys.path_importer_cache)
    assert sys.path == before and not dependencies._POOL and not dependencies._PACKAGES


@pytest.mark.asyncio
async def test_incompatible_active_profile_rejected_then_boots_after_owner_stops(profile, tmp_path):
    home, _ = profile
    second_profile(home, 'second')
    cli.run_plugin('python-test', ['add', str(project(tmp_path))])
    cli.run_plugin('second', ['add', str(project(tmp_path, version='2.0.0', library_version='2.0.0', text='second'))])
    first = await boot_profile(home)
    try:
        with pytest.raises(RuntimeError, match='active profile'):
            await boot_profile(home, 'second')
        assert await format_call(first, 'kept') == 'locked-sub:kept:1'
    finally:
        await close(first)
    second = await boot_profile(home, 'second')
    try:
        assert await format_call(second, 'new') == 'second-sub:new:1'
    finally:
        await close(second)
    assert not dependencies._POOL and not dependencies._PACKAGES


@pytest.mark.parametrize('failure', ['missing-leaf', 'wrong-version', 'hash', 'extra-code', 'extra-upper-code', 'syntax', 'native', 'bytecode', 'path-hook', 'root-collision', 'reserved-root', 'overlap', 'abi', 'platform', 'origin', 'unreachable', 'missing-source'])
def test_invalid_closure_never_imports_code_or_changes_profile(profile, tmp_path, failure):
    _, directory = profile
    source = project(tmp_path)
    path = source / 'package.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    lock = manifest['dsh']['pythonDependencies']
    helper, leaf = lock['packages']
    if failure == 'missing-leaf':
        lock['packages'].pop()
    elif failure == 'wrong-version':
        leaf['version'] = '2.0.0'
    elif failure == 'hash':
        helper['files']['test_helper/__init__.py'] = '0' * 64
    elif failure == 'extra-code':
        (source / 'vendor/test-helper/extra.py').write_text('raise AssertionError("never import")\n', encoding='utf-8')
    elif failure == 'extra-upper-code':
        body = b'raise AssertionError("never import uppercase hidden code")\n'
        (source / 'vendor/test-helper/json.PY').write_bytes(body)
        helper['files']['json.PY'] = hashlib.sha256(body).hexdigest()
        manifest['dsh']['release']['files'].append('vendor/test-helper/json.PY')
    elif failure == 'syntax':
        file = source / 'vendor/test-helper/test_helper/__init__.py'
        file.write_text('def broken(:\n', encoding='utf-8')
        helper['files']['test_helper/__init__.py'] = hashlib.sha256(file.read_bytes()).hexdigest()
    elif failure == 'native':
        (source / 'vendor/test-helper/forbidden.pyd').write_bytes(b'fixture')
    elif failure in ('bytecode', 'path-hook'):
        filename = 'json.pyc' if failure == 'bytecode' else 'hook.pth'
        body = b'opaque bytecode' if failure == 'bytecode' else b'import json\n'
        (source / 'vendor/test-helper' / filename).write_bytes(body)
        helper['files'][filename] = hashlib.sha256(body).hexdigest()
        manifest['dsh']['release']['files'].append('vendor/test-helper/' + filename)
    elif failure in ('root-collision', 'reserved-root'):
        root_name = 'json' if failure == 'root-collision' else '_dsh_python_fake'
        helper['imports'] = [root_name]
        old = source / 'vendor/test-helper/test_helper'
        old.rename(old.with_name(root_name))
        helper['files'] = {key.replace('test_helper/', root_name + '/'): value for key, value in helper['files'].items()}
    elif failure == 'overlap':
        helper['sourceRoot'] = 'python'
    elif failure in ('abi', 'platform', 'origin'):
        if failure == 'origin':
            helper['origin'] = ''
        else:
            lock[failure] = 'unsupported'
    elif failure == 'unreachable':
        helper['requires'] = []
    else:
        helper['sourceRoot'] = 'missing'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    before = (directory / 'package.json').read_bytes()
    with pytest.raises(ValueError):
        cli.run_plugin('python-test', ['add', str(source)])
    assert (directory / 'package.json').read_bytes() == before
    assert 'test_helper' not in sys.modules and 'test_leaf' not in sys.modules
    assert not dependencies._POOL and not dependencies._PACKAGES


@pytest.mark.parametrize('operation', ['add', 'upgrade', 'rollback'])
def test_profile_conflict_rejects_all_replacement_paths(profile, tmp_path, operation):
    _, directory = profile
    first = project(tmp_path)
    cli.run_plugin('python-test', ['add', str(first)])
    second = project(tmp_path, name='@example/another-echo', version='1.0.0')
    # A second identity changes only the conflicting library for add/upgrade.
    if operation == 'rollback':
        newer = project(tmp_path, version='2.0.0', library_version='2.0.0', text='new')
        cli.run_plugin('python-test', ['upgrade', str(newer)])
        second = project(tmp_path, name='@example/matching-new', version='1.0.0', library_version='2.0.0', text='new')
    cli.run_plugin('python-test', ['add', str(second)])
    before = (directory / 'package.json').read_bytes()
    conflict = project(tmp_path, name='@example/conflicting-echo', version='2.0.0', library_version='2.0.0', text='different')
    args = ['add', str(conflict)] if operation == 'add' else ['rollback', PACKAGE, '1.0.0'] if operation == 'rollback' else ['upgrade', str(project(tmp_path, version='3.0.0', library_version='3.0.0', text='different'))]
    with pytest.raises(ValueError, match='incompatible Python dependency'):
        cli.run_plugin('python-test', args)
    assert (directory / 'package.json').read_bytes() == before


@pytest.mark.asyncio
async def test_failed_host_import_releases_libraries_paths_namespaces_and_lock(profile, tmp_path):
    home, directory = profile
    source = project(tmp_path)
    file = source / 'python/echo/plugin.py'
    file.write_text('import test_helper\nraise RuntimeError("fixture import failed")\n', encoding='utf-8')
    before = sys.path[:]
    cli.run_plugin('python-test', ['add', str(source)])
    with pytest.raises(Exception, match='fixture import failed'):
        await boot_profile(home)
    assert sys.path == before and 'test_helper' not in sys.modules
    assert not dependencies._POOL and not dependencies._PACKAGES
    assert cli.run_plugin('python-test', ['remove', PACKAGE]) == 0


@pytest.mark.asyncio
async def test_libraries_stay_available_until_async_plugin_disposal_finishes(profile, tmp_path, monkeypatch):
    home, _ = profile
    source = project(tmp_path)
    control = types.ModuleType('dependency_disposal_fixture')
    control.entered, control.release, control.value = asyncio.Event(), asyncio.Event(), None
    monkeypatch.setitem(sys.modules, control.__name__, control)
    (source / 'python/echo/plugin.py').write_text('''from dsh.plugin_api import Plugin
import dependency_disposal_fixture as control
class EchoPlugin(Plugin):
    def apply(self, ctx, config):
        async def cleanup():
            control.entered.set()
            await control.release.wait()
            import test_helper
            control.value = test_helper.format('cleanup')
        ctx.effect(lambda: cleanup)
''', encoding='utf-8')
    cli.run_plugin('python-test', ['add', str(source)])
    result = await boot_profile(home)
    disposal = asyncio.ensure_future(result['ctx'].fiber.dispose())
    try:
        await asyncio.wait_for(control.entered.wait(), timeout=5)
        assert dependencies._POOL and not disposal.done()
        assert importlib.import_module('test_helper').format('pending') == 'locked-sub:pending:1'
    finally:
        control.release.set()
        await disposal
        await result['ctx'].fiber.await_settled()
        await asyncio.sleep(0)
    assert control.value == 'locked-sub:cleanup:2'
    assert not dependencies._POOL and not dependencies._PACKAGES


@pytest.mark.asyncio
async def test_changed_source_during_snapshot_rolls_back_all_runtime_registrations(profile, tmp_path, monkeypatch):
    home, directory = profile
    cli.run_plugin('python-test', ['add', str(project(tmp_path))])
    leaf = installed(directory) / 'vendor/test-leaf/test_leaf/__init__.py'
    original = leaf.read_bytes()
    before = sys.path[:]
    real_directory = dependencies.tempfile.TemporaryDirectory
    created = []
    def changing_directory(*args, **kwargs):
        temporary = real_directory(*args, **kwargs)
        created.append(Path(temporary.name))
        if len(created) == 2:
            leaf.write_bytes(b'PREFIX = "changed after validation"\n')
        return temporary
    monkeypatch.setattr(dependencies.tempfile, 'TemporaryDirectory', changing_directory)
    try:
        with pytest.raises(ValueError, match='changed during runtime preparation'):
            await boot_profile(home)
        assert sys.path == before and not dependencies._POOL and not dependencies._PACKAGES
        assert len(created) == 2 and all(not path.exists() for path in created)
    finally:
        leaf.write_bytes(original)
    assert cli.run_plugin('python-test', ['remove', PACKAGE]) == 0


def test_release_list_must_include_all_locked_dependency_files(profile, tmp_path):
    source = project(tmp_path)
    change(source, lambda manifest: manifest['dsh']['release']['files'].remove('vendor/test-helper/LICENSE'))
    output = tmp_path / 'omitted.zip'
    with pytest.raises(ValueError, match='release list omits required'):
        cli.run_plugin('python-test', ['pack', str(source), str(output)])
    assert not output.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows case-relaxed import behavior')
def test_windows_case_relaxed_module_aliases_are_owned_and_removed(profile, tmp_path):
    home, _ = profile
    cli.run_plugin('python-test', ['add', str(project(tmp_path))])
    root = Path(__file__).resolve().parents[1]
    script = '''import asyncio, importlib, sys
from dsh.boot import python_plugin_dependencies as dependencies
from test_python_plugin_dependencies import boot_profile
from test_python_plugin_distribution import close
async def main():
    result = await boot_profile(sys.argv[1])
    try:
        alias = importlib.import_module('TEST_HELPER')
        assert alias.format('alias') == 'locked-sub:alias:1'
        assert 'TEST_HELPER.sub' in sys.modules
    finally:
        await close(result)
    assert not any(name.casefold() == 'test_helper' or name.casefold().startswith('test_helper.') for name in sys.modules)
    assert not dependencies._POOL and not dependencies._PACKAGES
asyncio.run(main())
print('case-alias-cleaned')
'''
    environment = dict(os.environ, PYTHONCASEOK='1', PYTHONPATH=str(root / 'tests'))
    run = subprocess.run([sys.executable, '-c', script, str(home)], cwd=str(root), env=environment,
                         capture_output=True, encoding='utf-8', timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'case-alias-cleaned' in run.stdout


@pytest.mark.skipif(os.name != 'nt', reason='Windows uppercase Python extension')
def test_uppercase_python_source_is_validated_and_changes_import_identity(tmp_path):
    source = tmp_path / 'uppercase-source'
    shutil.copytree(str(EXAMPLE), str(source), ignore=shutil.ignore_patterns('__pycache__'))
    old = source / 'python/echo/formatting.py'
    upper = old.with_suffix('.PY')
    old.rename(upper)
    _, first = import_package(str(source))
    assert first.format_echo('one') == 'Python echo: one'
    upper.write_text('def format_echo(text):\n    return "Uppercase: " + text\n', encoding='utf-8')
    _, second = import_package(str(source))
    assert second is not first and second.format_echo('two') == 'Uppercase: two'
    upper.write_text('def broken(:\n', encoding='utf-8')
    with pytest.raises(ValueError, match='invalid Python syntax'):
        validate_sources(str(source))
