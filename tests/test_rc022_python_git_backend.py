import json
from pathlib import Path
import shutil

import pytest

from dsh.boot.python_package_prepare import prepared_git_package, read_prepared
from dsh.boot.python_plugin_acquisition import verified_record
from dsh.boot import python_plugins as store
from test_python_plugin_distribution import profile, close, echo, PACKAGE
from test_rc022_python_package_git import repository
from test_rc022_python_package_acquire import registry_package
from test_rc022_python_package_backend import start


def pinned(repository, commit=None):
    return repository['spec'] + '#' + (commit or repository['commit']) + '&path:plugin'


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', ['commit', 'repository', 'directory', 'manifest', 'files', 'archive', 'registry'])
async def test_parent_revalidates_git_origin_content_and_source_kind(profile, repository, tmp_path, damage):
    _, directory = profile
    spec = pinned(repository)
    async with prepared_git_package(str(directory), spec) as prepared:
        assert prepared.result['exitCode'] == 0, prepared.result
        output = Path(prepared.candidate.source).parent
        assert verified_record(prepared.candidate.source, prepared.candidate.acquisition) == prepared.candidate.acquisition
        with pytest.raises(ValueError):
            read_prepared(str(output))
        with pytest.raises(ValueError):
            read_prepared(str(output), local=True)
        receipt = output / 'prepared.json'
        value = json.loads(receipt.read_text(encoding='utf-8'))
        if damage in ('commit', 'repository', 'directory'):
            value['git'][damage] = dict(commit='1' * 40, repository='https://example.invalid/other/repo.git', directory='other')[damage]
        elif damage == 'manifest':
            value['manifest']['version'] = '9.0.0'
        elif damage == 'files':
            value['files']['package.json'] = '0' * 64
        elif damage == 'archive':
            Path(prepared.candidate.source).write_bytes(b'changed')
        else:
            value['acquisition'] = prepared.candidate.acquisition
            value.pop('files');value.pop('archive');value.pop('git');value['formatVersion'] = 1
        receipt.write_text(json.dumps(value), encoding='utf-8')
        with pytest.raises(ValueError):
            read_prepared(str(output), git_spec=spec)
        if damage == 'registry':
            with pytest.raises(ValueError):
                read_prepared(str(output))
    assert not (directory / '.dsh-python-downloads').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'disabled', 'invalid-abi', 'activation-error'])
async def test_actual_manager_git_install_update_and_offline_origin_restoration(profile, repository, registry_package, mode):
    home, directory = profile
    host = await start(home, registry_package)
    ctx = host['ctx']
    # Only Git is on the native child's PATH; Python is an absolute executable.
    ctx.profilePackages.config['env']['PATH'] = str(Path(shutil.which('git')).parent)
    logs = []
    ctx.on('plugin-manager/install-log', logs.append)
    try:
        result = await ctx.pluginManager.installBundle(pinned(repository), dict(enabled=mode != 'disabled'))
        assert result['application'] == 'applied', result
        original = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
        old_record = original['dsh']['pythonPlugins'][PACKAGE]
        assert original['dependencies'][PACKAGE] == pinned(repository)
        assert old_record['acquisition']['kind'] == 'git-tgz' and old_record['acquisition']['commit'] == repository['commit']
        row = next(row for row in await ctx.pluginManager.listBundles() if row['name'] == PACKAGE)
        assert row['source'] == pinned(repository)
        if mode != 'disabled':
            assert await echo(ctx) == 'Python echo: hello'
        package = repository['source'] / 'plugin'
        descriptor = package / 'package.json'
        manifest = json.loads(descriptor.read_text(encoding='utf-8'))
        manifest['version'] = '0.2.0'
        if mode == 'invalid-abi':
            manifest['dsh'].pop('python')
        descriptor.write_text(json.dumps(manifest), encoding='utf-8')
        (package / 'python/echo/formatting.py').write_text('def format_echo(text):\n    return "Git updated: " + text\n', encoding='utf-8')
        if mode == 'activation-error':
            code = package / 'python/echo/plugin.py'
            code.write_text(code.read_text(encoding='utf-8').replace('    def apply(self, ctx, config):', '    def apply(self, ctx, config):\n        raise RuntimeError("Git activation refused")'), encoding='utf-8')
        repository['git']('add', '.')
        repository['git']('commit', '-m', 'next native Git version')
        commit = repository['git']('rev-parse', 'HEAD')
        next_spec = pinned(repository, commit)
        logs.clear()
        result = await ctx.pluginManager.updateBundle(PACKAGE, '0.2.0', dict(spec=next_spec, requestId='git-update'))
        assert result['from'] == '0.1.0' and result['to'] == '0.2.0' and result['step'] == 'install', result
        current = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
        if mode in ('success', 'disabled'):
            assert result['result']['application'] == 'applied' and 'restore' not in result, result
            assert current['dependencies'][PACKAGE] == next_spec
            assert current['dsh']['pythonPlugins'][PACKAGE]['acquisition']['commit'] == commit
            if mode == 'success':
                assert await echo(ctx) == 'Git updated: hello'
            else:
                assert ctx.tools.get('python_echo') is None
        else:
            assert result['result']['application'] == 'failed' and result['restore']['application'] == 'applied', result
            assert current['dsh']['pythonPlugins'][PACKAGE] == old_record and current['dependencies'][PACKAGE] == pinned(repository)
            assert await echo(ctx) == 'Python echo: hello'
            restored_logs = [row['text'] for row in logs if 'requestId' not in row]
            assert any('Restored ' + PACKAGE in line for line in restored_logs)
            assert not any('Fetching Git source' in line for line in restored_logs)
        assert registry_package['requests'] == []
        assert not ctx.profilePackages.updates and not ctx.profilePackages.operations
        assert not (directory / '.dsh-python-downloads').exists() and not (directory / '.dsh-python-updates').exists()
        assert (await ctx.pluginManager.removeBundle(PACKAGE))['application'] == 'applied'
    finally:
        await close(host)


def test_git_persisted_identity_refuses_credentials_unpinned_commits_and_unsafe_paths():
    base = dict(kind='git-tgz', repository='https://example.invalid/owner/repo.git', commit='a' * 40,
        directory='plugin', sha256='0' * 64, bytes=1)
    assert store.dependency_reference(PACKAGE, dict(acquisition=base)).endswith('#' + 'a' * 40 + '&path:plugin')
    for change in (dict(repository='https://user:secret@example.invalid/owner/repo.git'),
            dict(commit='main'), dict(directory='../escape')):
        with pytest.raises(ValueError):
            store.dependency_reference(PACKAGE, dict(acquisition=dict(base, **change)))
