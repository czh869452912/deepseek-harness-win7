import asyncio
import hashlib
import json
from pathlib import Path
import threading

import pytest

from apps.cli import plugin as cli
from dsh.boot.python_package_prepare import prepared_url_package, read_prepared
from dsh.boot.python_package_tarball import downloaded_url_tarball
from dsh.boot.python_plugin_acquisition import verified_record
from dsh.boot.profile import read_profile_manifest
from dsh.core.abort import AbortController, AbortError
from test_python_plugin_distribution import profile, close, echo, PACKAGE
from test_rc022_python_package_acquire import registry_package
from test_rc022_python_package_backend import start
from test_rc022_python_native_cli import invoke, native_environment
from test_rc022_python_package_update import next_version


def options(state):
    certificate = Path(__file__).parent / 'fixtures/tls/localhost-cert.pem'
    return dict(env=dict(state['env'], PATH='', SSL_CERT_FILE=str(certificate.resolve())))


@pytest.mark.asyncio
async def test_actual_manager_remote_tarball_install_execute_and_remove(profile, registry_package):
    home, directory = profile
    host = await start(home, registry_package)
    ctx = host['ctx'];spec = registry_package['url'] + '/archive.tgz'
    try:
        result = await ctx.pluginManager.installBundle(spec)
        assert result['application'] == 'applied', result
        assert await echo(ctx) == 'Python echo: hello'
        manifest = read_profile_manifest('dsh', str(directory))
        record = manifest['dsh']['pythonPlugins'][PACKAGE]['acquisition']
        assert manifest['dependencies'][PACKAGE] == spec and record['kind'] == 'url-tgz'
        assert record['sha256'] == hashlib.sha256(registry_package['payload']).hexdigest()
        assert 'integrity' not in record and set(registry_package['requests']) == {'/archive.tgz'}
        update = await ctx.pluginManager.updateBundle(PACKAGE, '0.2.0')
        assert update['step'] == 'check' and update['result']['error']['code'] == 'invalid-spec'
        assert await echo(ctx) == 'Python echo: hello'
        assert (await ctx.pluginManager.removeBundle(PACKAGE))['application'] == 'applied'
    finally:
        await close(host)


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', ['archive', 'manifest', 'url', 'kind', 'integrity'])
async def test_parent_rejects_remote_publication_tampering_and_registry_confusion(profile, registry_package, damage):
    _, directory = profile
    spec = registry_package['url'] + '/archive.tgz'
    async with prepared_url_package(str(directory), spec, options(registry_package)) as prepared:
        assert prepared.result['exitCode'] == 0, prepared.result
        assert verified_record(prepared.candidate.source, prepared.candidate.acquisition) == prepared.candidate.acquisition
        output = Path(prepared.candidate.source).parent;receipt = output / 'prepared.json'
        with pytest.raises(ValueError):read_prepared(str(output))
        with pytest.raises(ValueError):read_prepared(str(output), local=True)
        value = json.loads(receipt.read_text(encoding='utf-8'))
        if damage == 'archive':Path(prepared.candidate.source).write_bytes(b'changed')
        elif damage == 'manifest':value['manifest']['name'] = '@other/package'
        elif damage == 'url':value['acquisition']['url'] = 'https://example.invalid/other.tgz'
        elif damage == 'kind':value['formatVersion'] = 1
        else:value['acquisition']['integrity'] = 'invented registry evidence'
        receipt.write_text(json.dumps(value), encoding='utf-8')
        with pytest.raises(ValueError):read_prepared(str(output), url_spec=spec)
        if damage == 'kind':
            with pytest.raises(ValueError):read_prepared(str(output))
    assert not (directory / '.dsh-python-downloads').exists()


@pytest.mark.asyncio
async def test_actual_remote_download_cancel_drains_and_cleans_partial_payload(profile, registry_package):
    _, directory = profile
    state = registry_package;state['pause'], state['entered'] = threading.Event(), threading.Event()
    controller = AbortController();before = (directory / 'package.json').read_bytes()
    async def run():
        try:
            async with prepared_url_package(str(directory), state['url'] + '/archive.tgz',
                    dict(options(state), signal=controller.signal)) as prepared:
                assert prepared.candidate is None
        except AbortError:
            assert controller.signal.aborted
    task = asyncio.create_task(run())
    try:
        for _ in range(500):
            if state['entered'].is_set():break
            await asyncio.sleep(.02)
        assert state['entered'].is_set()
        controller.abort()
        await asyncio.wait_for(task, 3)
    finally:
        state['pause'].set()
        controller.abort()
        await asyncio.gather(task, return_exceptions=True)
    assert not (directory / '.dsh-python-downloads').exists() and not list(directory.rglob('run.json'))
    assert (directory / 'package.json').read_bytes() == before


def test_direct_transfer_records_raw_bytes_and_redacts_query_without_claiming_sri(registry_package):
    url = registry_package['url'] + '/archive.tgz?token=fixture-secret'
    with downloaded_url_tarball(url) as (source, record):
        assert record == dict(kind='url-tgz', url=url.split('?')[0],
            sha256=hashlib.sha256(registry_package['payload']).hexdigest(), bytes=len(registry_package['payload']))
        assert verified_record(source, record) == record
    assert not Path(source).exists()


@pytest.mark.parametrize('failure', ['abi', 'engines', 'invalid-archive'])
@pytest.mark.asyncio
async def test_invalid_remote_native_package_preserves_profile(profile, registry_package, failure):
    _, directory = profile;state = registry_package
    if failure == 'invalid-archive':state['payload'] = b'not a tarball'
    else:
        if failure == 'abi':state['metadata']['dsh'].pop('python')
        else:state['metadata']['engines'] = dict(dsh='>=99.0.0')
        state['pack'](state['metadata'])
    before = (directory / 'package.json').read_bytes()
    async with prepared_url_package(str(directory), state['url'] + '/archive.tgz', options(state)) as prepared:
        assert prepared.result['exitCode'] != 0 and prepared.candidate is None
    assert (directory / 'package.json').read_bytes() == before and not (directory / '.dsh-python-downloads').exists()


def test_canonical_cli_direct_tarball_upgrade_and_offline_source_rollback(profile, registry_package, monkeypatch):
    _, directory = profile;state = registry_package;native_environment(monkeypatch, state)
    spec = state['url'] + '/archive.tgz'
    assert invoke(monkeypatch, 'add', spec) == 0
    old = read_profile_manifest('dsh', str(directory))['dsh']['pythonPlugins'][PACKAGE]['acquisition']
    next_version(state)
    assert invoke(monkeypatch, 'upgrade', spec) == 0
    requests = list(state['requests'])
    assert invoke(monkeypatch, 'rollback', PACKAGE, '0.1.0') == 0
    assert state['requests'] == requests
    restored = read_profile_manifest('dsh', str(directory))
    assert restored['dependencies'][PACKAGE] == spec and restored['dsh']['pythonPlugins'][PACKAGE]['acquisition'] == old
    assert invoke(monkeypatch, 'remove', PACKAGE) == 0
