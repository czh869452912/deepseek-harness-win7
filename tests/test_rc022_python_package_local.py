import asyncio
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from dsh.boot.python_package_prepare import prepared_local_package, read_prepared
from dsh.core.abort import AbortController, AbortError
from test_python_plugin_distribution import profile, close, echo, EXAMPLE, PACKAGE
from test_python_plugin_dependencies import project
from test_rc022_python_package_acquire import registry_package
from test_rc022_python_package_backend import start
from test_rc022_python_package_tarball import package_archive


def local_source(tmp_path, kind):
    if kind == 'directory':
        source = tmp_path / 'reviewed source with spaces'
        shutil.copytree(str(EXAMPLE), str(source), ignore=shutil.ignore_patterns('__pycache__'))
        return source
    if kind == 'tarball':
        return package_archive(tmp_path / 'reviewed.tgz')
    source = tmp_path / 'reviewed.zip'
    with zipfile.ZipFile(str(source), 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in json.loads((EXAMPLE / 'package.json').read_text(encoding='utf-8'))['dsh']['release']['files']:
            archive.write(str(EXAMPLE / name), name)
    return source


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['directory', 'zip', 'tarball'])
async def test_actual_local_manager_install_execute_unload_without_registry_request(profile, registry_package, tmp_path, kind):
    home, directory = profile
    source = local_source(tmp_path, kind)
    host = await start(home, registry_package)
    try:
        result = await host['ctx'].pluginManager.installBundle(str(source))
        assert result['application'] == 'applied', result
        assert result['packageResult']['nativeCommitted'] and result['bundle'] == PACKAGE
        assert await echo(host['ctx']) == 'Python echo: hello'
        assert registry_package['requests'] == []
        assert not (directory / '.dsh-python-downloads').exists()
        assert (await host['ctx'].pluginManager.removeBundle(PACKAGE))['application'] == 'applied'
        assert not (directory / 'node_modules' / PACKAGE).exists()
    finally:
        await close(host)


@pytest.mark.asyncio
async def test_local_child_copies_locked_libraries_without_importing_author_code(profile, tmp_path):
    _, directory = profile
    source = project(tmp_path)
    sentinel = tmp_path / 'imported.txt'
    code = source / 'python/echo/plugin.py'
    code.write_text('from pathlib import Path\nPath(' + repr(str(sentinel)) + ').write_text("executed",encoding="utf-8")\n' + code.read_text(encoding='utf-8'), encoding='utf-8')
    before = (directory / 'package.json').read_bytes()
    async with prepared_local_package(str(directory), str(source), dict(env=dict(PATH=''))) as prepared:
        assert prepared.result['exitCode'] == 0 and prepared.candidate.acquisition is None, prepared.result
        assert prepared.candidate.manifest['dsh']['python']['dependencies'] == ['test-helper==1.0.0']
        assert not sentinel.exists() and (directory / 'package.json').read_bytes() == before
        output = Path(prepared.candidate.source).parent
        assert read_prepared(str(output), local=True).manifest == prepared.candidate.manifest
        with pytest.raises(ValueError):
            read_prepared(str(output))
    assert not (directory / '.dsh-python-downloads').exists() and not sentinel.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', ['archive', 'files', 'manifest', 'origin'])
async def test_parent_checks_local_archive_content_identity_and_receipt(profile, tmp_path, damage):
    _, directory = profile
    source = local_source(tmp_path, 'directory')
    async with prepared_local_package(str(directory), str(source), dict(env=dict(PATH=''))) as prepared:
        assert prepared.result['exitCode'] == 0
        output = Path(prepared.candidate.source).parent
        receipt = output / 'prepared.json'
        value = json.loads(receipt.read_text(encoding='utf-8'))
        if damage == 'archive':
            Path(prepared.candidate.source).write_bytes(b'changed')
        if damage == 'files':
            value['files']['README.md'] = '0' * 64
        if damage == 'manifest':
            value['manifest']['version'] = '9.0.0'
        if damage == 'origin':
            value['acquisition'] = dict(kind='registry-tgz')
        receipt.write_text(json.dumps(value), encoding='utf-8')
        with pytest.raises(ValueError):
            read_prepared(str(output), local=True)
    assert not (directory / '.dsh-python-downloads').exists()


@pytest.mark.asyncio
async def test_local_preparation_can_be_cancelled_before_any_profile_commit(profile, tmp_path):
    _, directory = profile
    source = local_source(tmp_path, 'directory')
    controller = AbortController()
    before = (directory / 'package.json').read_bytes()
    async def run():
        try:
            async with prepared_local_package(str(directory), str(source), dict(env=dict(PATH=''), signal=controller.signal,
                    onOutput=lambda text, stream: controller.abort() if 'Preparing local' in text else None)) as prepared:
                assert prepared.candidate is None and prepared.result['exitCode'] != 0
        except AbortError:
            assert controller.signal.aborted
    await asyncio.wait_for(run(), 5)
    assert controller.signal.aborted and (directory / 'package.json').read_bytes() == before
    assert not (directory / '.dsh-python-downloads').exists() and not list(directory.rglob('run.json'))


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', ['abi', 'engines'])
async def test_invalid_or_incompatible_local_source_is_refused_before_commit(profile, registry_package, tmp_path, damage):
    home, directory = profile
    source = local_source(tmp_path, 'directory')
    descriptor = source / 'package.json'
    value = json.loads(descriptor.read_text(encoding='utf-8'))
    if damage == 'abi':
        value['dsh'].pop('python')
    else:
        value['engines'] = dict(dsh='>=99.0.0')
    descriptor.write_text(json.dumps(value), encoding='utf-8')
    host = await start(home, registry_package)
    before = (directory / 'package.json').read_bytes()
    try:
        result = await host['ctx'].pluginManager.installBundle(str(source))
        assert result['application'] == 'failed' and not result['changed'], result
        if damage == 'engines':
            assert result['error']['code'] == 'incompatible-version', result
        assert (directory / 'package.json').read_bytes() == before and not (directory / 'node_modules' / PACKAGE).exists()
        assert not (directory / '.dsh-python-downloads').exists() and registry_package['requests'] == []
    finally:
        await close(host)


@pytest.mark.asyncio
async def test_local_unicode_source_and_pax_member_names_round_trip(profile, tmp_path):
    _, directory = profile
    original = local_source(tmp_path, 'directory')
    source = original.with_name('本地 插件源')
    original.rename(source)
    asset = source / 'assets/说明.txt'
    asset.parent.mkdir()
    asset.write_text('源文件内容', encoding='utf-8')
    descriptor = source / 'package.json'
    manifest = json.loads(descriptor.read_text(encoding='utf-8'))
    manifest['dsh']['release']['files'].append('assets/说明.txt')
    descriptor.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    async with prepared_local_package(str(directory), str(source), dict(env=dict(PATH=''))) as prepared:
        assert prepared.result['exitCode'] == 0, prepared.result
        value = json.loads((Path(prepared.candidate.source).parent / 'prepared.json').read_text(encoding='utf-8'))
        assert 'assets/说明.txt' in value['files'] and prepared.candidate.manifest == manifest
    assert not (directory / '.dsh-python-downloads').exists()
