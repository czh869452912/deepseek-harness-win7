"""Install prebuilt Client/Remote artifacts through the actual Web composition."""
import asyncio
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import zipfile

import pytest

from apps.cli import plugin as cli
from canonical_web_fixture import web_context, close_web_context
from dsh.boot.python_package import validate_sources
from dsh.boot.profile import read_profile_manifest
from dsh.core.abort import NEVER_ABORTED
from dsh.plugin_api import JsonSchemaCodec
from dsh.typert.dispatch import RemoteDispatcher, TypertGatewayError

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'examples/python-web-echo'
NAME = '@example/python-web-echo'


def archive_project(project, destination):
    assert cli.run_plugin('web', ['pack', str(project), str(destination)]) == 0


async def prepare_home(home, monkeypatch):
    ctx = await web_context(home)
    await close_web_context(ctx)
    monkeypatch.setenv('DSH_HOME', str(home))
    real_which = shutil.which
    monkeypatch.setattr(cli.shutil, 'which', lambda name, *args, **kwargs:
        None if name in ('node', 'pnpm') else real_which(name, *args, **kwargs))


async def settle(ctx):
    for _ in range(20):
        await asyncio.sleep(0)


async def echo(ctx, text):
    return await RemoteDispatcher(ctx).invoke(dict(namespace='pythonWebEcho', method='echo',
        args=dict(text=text), signal=NEVER_ABORTED))


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['directory', 'zip'])
async def test_native_web_package_install_remote_withdraw_restart_remove(tmp_path, monkeypatch, kind):
    home = tmp_path / 'home'
    await prepare_home(home, monkeypatch)
    source = PROJECT
    if kind == 'zip':
        source = tmp_path / 'example.zip'
        archive_project(PROJECT, source)
    assert cli.run_plugin('web', ['add', str(source)]) == 0
    for generation in range(2):
        ctx = await web_context(home)
        try:
            assert NAME in {row['id'] for row in ctx.clientModules.graph()['entries']}
            assert ctx.typert.local.get('pythonWebEcho/echo')['result']['mode'] == 'strict'
            assert await echo(ctx, '中文') == dict(text='Python Web echo: 中文', calls=1, version='1.0.0')
            assert await echo(ctx, 'again') == dict(text='Python Web echo: again', calls=2, version='1.0.0')
            with pytest.raises(TypertGatewayError, match='boundary validation'):
                await echo(ctx, 123)
            assert ctx.get('pythonWebEcho').calls == 2
            entry = next(row for row in ctx.loader.entries if row.options.get('name') == NAME)
            await entry.fiber.dispose()
            await entry.fiber.await_settled()
            await settle(ctx)
            assert ctx.get('pythonWebEcho') is None
            assert NAME not in {row['id'] for row in ctx.clientModules.graph()['entries']}
            assert ctx.typert.local.get('pythonWebEcho/echo') is None
            with pytest.raises(TypertGatewayError, match='withdrawn'):
                await echo(ctx, 'after unload')
        finally:
            await close_web_context(ctx)
    assert cli.run_plugin('web', ['remove', NAME]) == 0
    ctx = await web_context(home)
    try:
        assert ctx.get('pythonWebEcho') is None
        assert NAME not in {row['id'] for row in ctx.clientModules.graph()['entries']}
    finally:
        await close_web_context(ctx)


@pytest.mark.parametrize('change, message', [
    ('bundle', 'differs from its build receipt'), ('map', 'differs from its build receipt'),
    ('contract', 'differs from its build receipt'), ('artifact', 'differs from its build receipt'),
    ('missing', 'missing'), ('receipt', 'build receipt'), ('target', 'pinned Host protocol'),
    ('export', 'relative ./client'), ('escape', 'invalid package path'), ('map-omitted', 'source map'),
])
def test_web_build_inputs_rejected_before_profile_commit(tmp_path, monkeypatch, change, message):
    project = tmp_path / 'project'
    shutil.copytree(str(PROJECT), str(project))
    manifest = json.loads((project / 'package.json').read_text(encoding='utf-8'))
    if change in ('bundle', 'map', 'contract', 'artifact'):
        relative = dict(bundle='client/client.js', map='client/client.js.map', contract='remote/contract.json', artifact='remote/typert.py')[change]
        with (project / relative).open('a', encoding='utf-8') as stream:
            stream.write('\nchanged')
    elif change == 'missing':
        (project / 'client/client.js').unlink()
    elif change == 'receipt':
        del manifest['dsh']['webArtifacts']
    elif change == 'target':
        manifest['dsh']['webArtifacts']['targetUpstream'] = '0' * 40
    elif change == 'export':
        del manifest['exports']['./client']
    elif change == 'escape':
        manifest['dsh']['webArtifacts']['files']['../escape.js'] = '0' * 64
    else:
        del manifest['dsh']['webArtifacts']['files']['client/client.js.map']
    (project / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    from dsh.boot.profile import init_profile
    home = tmp_path / 'home'
    profile = home / 'profiles/web'
    init_profile(str(profile), [], 'startup')
    monkeypatch.setenv('DSH_HOME', str(home))
    before = (profile / 'package.json').read_bytes()
    with pytest.raises(ValueError, match=message):
        cli.run_plugin('web', ['add', str(project)])
    assert (profile / 'package.json').read_bytes() == before
    assert NAME not in read_profile_manifest('dsh', str(profile)).get('dsh', {}).get('pythonPlugins', {})


def test_shared_schema_codec_validation_and_no_mutation():
    codec = JsonSchemaCodec(dict(type='object', properties=dict(text=dict(type='string')),
        required=['text'], additionalProperties=False))
    value = dict(text='中文')
    parsed = codec.parse(value)
    assert parsed == value and parsed is not value
    with pytest.raises(ValueError):
        codec.parse(dict(text=123))
    projected = codec.to_json_schema()
    projected['properties']['text']['type'] = 'integer'
    assert codec.parse(value) == value


@pytest.mark.parametrize('change', ['missing-client', 'missing-contract', 'missing-remote',
    'missing-source', 'missing-license', 'duplicate-case', 'two-descriptors', 'invalid-version', 'null-release'])
def test_authored_release_is_complete_and_unambiguous(tmp_path, change):
    project = tmp_path / 'project'
    shutil.copytree(str(PROJECT), str(project))
    manifest = json.loads((project / 'package.json').read_text(encoding='utf-8'))
    release = manifest['dsh']['release']
    if change.startswith('missing-'):
        relative = {'missing-client': 'client/client.js', 'missing-contract': 'remote/contract.json',
            'missing-remote': 'remote/typert.py', 'missing-source': 'python/web_echo/plugin.py',
            'missing-license': 'LICENSE'}[change]
        release['files'].remove(relative)
    elif change == 'duplicate-case':
        release['files'].append('README.MD')
    elif change == 'two-descriptors':
        manifest['dsh']['sourceExport'] = dict(record='dsh-export.json', files=release['files'])
    elif change == 'null-release':
        manifest['dsh']['release'] = None
    else:
        release['formatVersion'] = True
    (project / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    output = tmp_path / 'bad.zip'
    with pytest.raises(ValueError):
        cli.run_plugin('web', ['pack', str(project), str(output)])
    assert not output.exists()


@pytest.mark.asyncio
async def test_authored_release_private_files_excluded_and_bad_upgrade_preserves_web(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    shutil.copytree(str(PROJECT), str(project))
    (project / '.env').write_text('PRIVATE=example-not-a-credential\n', encoding='utf-8')
    (project / '.venv').mkdir()
    (project / '.venv/developer.txt').write_text('not a release asset', encoding='utf-8')
    output = tmp_path / 'plugin.zip'
    archive_project(project, output)
    with zipfile.ZipFile(str(output)) as archive:
        assert set(archive.namelist()) == set(json.loads((project / 'package.json').read_text(encoding='utf-8'))['dsh']['release']['files'])
    home = tmp_path / 'home'
    await prepare_home(home, monkeypatch)
    assert cli.run_plugin('web', ['add', str(project)]) == 0
    installed = home / 'profiles/web/node_modules/@example/python-web-echo'
    assert not (installed / '.env').exists() and not (installed / '.venv').exists()
    before = (home / 'profiles/web/package.json').read_bytes()
    with zipfile.ZipFile(str(output), 'a') as archive:
        archive.writestr('.env', 'PRIVATE=not-declared')
    with pytest.raises(ValueError, match='outside its explicit release list'):
        cli.run_plugin('web', ['upgrade', str(output)])
    assert (home / 'profiles/web/package.json').read_bytes() == before
    ctx = await web_context(home)
    try:
        assert await echo(ctx, 'retained') == dict(text='Python Web echo: retained', calls=1, version='1.0.0')
    finally:
        await close_web_context(ctx)


def test_example_build_receipt_and_artifact_match_pinned_target():
    manifest = validate_sources(str(PROJECT))
    receipt = manifest['dsh']['webArtifacts']
    assert receipt['targetUpstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    for file, digest in receipt['files'].items():
        assert hashlib.sha256((PROJECT / file).read_bytes()).hexdigest() == digest


def test_rebuilt_artifact_receipt_survives_lf_checkout(tmp_path):
    from scripts.build_python_web_example import build
    project = tmp_path / 'project'
    shutil.copytree(str(PROJECT), str(project))
    build(project)
    manifest = validate_sources(str(project))
    for file, digest in manifest['dsh']['webArtifacts']['files'].items():
        data = (project / file).read_bytes()
        assert b'\r\n' not in data
        assert hashlib.sha256(data).hexdigest() == digest


@pytest.mark.parametrize('change, message', [('syntax', 'invalid Python syntax'),
    ('empty-client', 'must not be empty'), ('source-map', 'Source Map'), ('hash', 'SHA-256')])
def test_consistent_receipt_does_not_bypass_artifact_validation(tmp_path, change, message):
    project = tmp_path / 'project'
    shutil.copytree(str(PROJECT), str(project))
    manifest = json.loads((project / 'package.json').read_text(encoding='utf-8'))
    files = manifest['dsh']['webArtifacts']['files']
    if change == 'hash':
        files['remote/typert.py'] = 'g' * 64
    else:
        relative, data = {'syntax': ('remote/typert.py', b'def broken(:\n'),
            'empty-client': ('client/client.js', b' \n'),
            'source-map': ('client/client.js.map', b'{"version":2}') }[change]
        (project / relative).write_bytes(data)
        files[relative] = hashlib.sha256(data).hexdigest()
    (project / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match=message):
        validate_sources(str(project))


@pytest.mark.skipif(not os.environ.get('DSH_TEST_CHROMIUM'), reason='real browser lane: set DSH_TEST_CHROMIUM')
def test_original_browser_installed_python_web_package_journey(tmp_path):
    node = shutil.which('node')
    assert node, 'developer browser lane requires Node with global WebSocket'
    output = tmp_path / 'python-web-browser.json'
    result = subprocess.run([node, str(ROOT / 'scripts/python_web_plugin_browser_oracle.mjs'),
        '--browser', os.environ['DSH_TEST_CHROMIUM'], '--output', str(output)], cwd=str(ROOT),
        capture_output=True, encoding='utf-8', timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['passed'] and report['python'] == '3.8.10'
    assert report['hostExitCode'] == 0 and not report['hostErrors']
    assert not report['errors'] and not report['consoleErrors'] and not report['requests']
    assert '/api/remote.mux' in report['sockets'] and len(report['replies']) == 6
    steps = {row['step'] for row in report['steps'] if row['passed']}
    assert {'host-unload-withdraws-strict-remote-retained-client-call-rejected',
        'page-refresh-removes-unloaded-client-from-original-boot-graph',
        'restart-from-installed-package', 'upgrade-from-installed-package',
        'rollback-from-installed-package', 'remove-from-installed-package'} <= steps
