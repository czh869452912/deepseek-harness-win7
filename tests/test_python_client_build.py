"""Actual creative source export, original evaluator packaging, native install."""
import hashlib
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from apps.cli import plugin as cli
from apps.cli.args import parse_dsh_args
from canonical_web_fixture import web_context, close_web_context
from dsh.boot.python_package import validate_sources
from dsh.core.abort import NEVER_ABORTED
from dsh.extensions.packaged_host import host_handler_service, host_remote_namespace, python_host_source
from dsh.typert.dispatch import RemoteDispatcher, TypertGatewayError
from scripts.python_export_client_fixture import NAME, HOST_SOURCE, CLIENT_SOURCE, export_project_at

ROOT = Path(__file__).resolve().parents[1]


async def call(ctx, method, args):
    return await RemoteDispatcher(ctx).invoke(dict(namespace=host_remote_namespace(NAME),
        method='call', args=dict(method=method, args=args), signal=NEVER_ABORTED))


@pytest.mark.asyncio
async def test_owned_export_native_build_pack_install_unload_restart(tmp_path, monkeypatch):
    project, source_receipt = await export_project_at(tmp_path)
    old_origin = json.loads((project / 'dsh-export.json').read_text(encoding='utf-8'))
    assert old_origin['requiresClientBuild']
    real_which = shutil.which
    monkeypatch.setattr(cli.shutil, 'which', lambda name, *args, **kwargs:
        None if name in ('node', 'pnpm') else real_which(name, *args, **kwargs))
    assert cli.run_plugin('web', ['build', str(project)]) == 0
    descriptor = validate_sources(str(project))
    origin = json.loads((project / 'dsh-export.json').read_text(encoding='utf-8'))
    assert not origin['requiresClientBuild'] and origin['sourceSha256'] == old_origin['sourceSha256']
    assert origin['packageId'] == source_receipt['packageId']
    assert (project / 'client/source.js').read_bytes() == CLIENT_SOURCE.encode('utf-8')
    assert (project / 'python/exported/host.body.py').read_bytes() == HOST_SOURCE.encode('utf-8')
    for relative, digest in descriptor['dsh']['webArtifacts']['files'].items():
        assert hashlib.sha256((project / relative).read_bytes()).hexdigest() == digest
    archive = tmp_path / 'built.zip'
    assert cli.run_plugin('web', ['pack', str(project), str(archive)]) == 0
    home = tmp_path / 'installed-home'
    monkeypatch.setenv('DSH_HOME', str(home))
    assert cli.run_plugin('web', ['add', str(archive)]) == 0
    for generation in range(2):
        ctx = await web_context(home)
        try:
            assert NAME in {row['id'] for row in ctx.clientModules.graph()['entries']}
            assert await call(ctx, 'echo', dict(text='中文')) == dict(text='Python Web echo: 中文', calls=1, version='1.0.0')
            assert await call(ctx, 'snapshot', None) == dict(calls=1, args=None)
            with pytest.raises(TypertGatewayError, match='boundary validation'):
                await call(ctx, 123, None)
            with pytest.raises(ValueError, match='unknown exported Host handler'):
                await call(ctx, 'missing', None)
            handlers = ctx.get(host_handler_service(NAME))
            remote = ctx.get(host_remote_namespace(NAME))
            entry = next(row for row in ctx.loader.entries if row.options.get('name') == NAME)
            await entry.fiber.dispose()
            await entry.fiber.await_settled()
            assert ctx.get(host_handler_service(NAME)) is None
            assert ctx.get(host_remote_namespace(NAME)) is None
            with pytest.raises(RuntimeError, match='unloaded'):
                await remote.call('snapshot', None)
            with pytest.raises(TypertGatewayError, match='withdrawn'):
                await call(ctx, 'snapshot', None)
            assert handlers.closed
        finally:
            await close_web_context(ctx)


@pytest.mark.asyncio
async def test_build_rejects_session_placement_without_promoting_host(tmp_path):
    project, _ = await export_project_at(tmp_path, placement='session')
    before = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='session Remote ownership'):
        cli.run_plugin('web', ['build', str(project)])
    assert {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()} == before


@pytest.mark.asyncio
async def test_client_only_export_build_uses_empty_host_and_independent_remote(tmp_path, monkeypatch):
    project, _ = await export_project_at(tmp_path, host_source=None, client_source='return function(ctx) {};')
    assert cli.run_plugin('web', ['build', str(project)]) == 0
    home = tmp_path / 'installed-home'
    monkeypatch.setenv('DSH_HOME', str(home))
    assert cli.run_plugin('web', ['add', str(project)]) == 0
    ctx = await web_context(home)
    try:
        assert ctx.get(host_remote_namespace(NAME)) is not None
        with pytest.raises(ValueError, match='unknown exported Host handler'):
            await call(ctx, 'missing', None)
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_rebuild_source_and_candidate_validation_preserve_existing_outputs(tmp_path):
    project, _ = await export_project_at(tmp_path)
    cli.run_plugin('web', ['build', str(project)])
    body = project / 'python/exported/host.body.py'
    body.write_text('def invalid(:\n', encoding='utf-8')
    outputs = {relative: (project / relative).read_bytes() for relative in
        ('package.json', 'dsh-export.json', 'client/client.js', 'remote/typert.py', 'python/exported/plugin.py')}
    with pytest.raises(ValueError, match='invalid Python syntax'):
        cli.run_plugin('web', ['build', str(project)])
    assert {relative: (project / relative).read_bytes() for relative in outputs} == outputs
    body.write_bytes(HOST_SOURCE.replace("'1.0.0'", "'2.0.0'").encode('utf-8'))
    cli.run_plugin('web', ['build', str(project)])
    validate_sources(str(project))
    (project / 'client/source.js').write_text(CLIENT_SOURCE + '\n// edited\n', encoding='utf-8')
    with pytest.raises(ValueError, match='differs from its build receipt'):
        validate_sources(str(project))
    cli.run_plugin('web', ['build', str(project)])
    validate_sources(str(project))


def test_build_cli_argument_contract():
    for args in (['build'], ['build', 'one', 'two']):
        with pytest.raises(ValueError, match='use build'):
            cli.run_plugin('web', args)
    parsed = parse_dsh_args(['plugin', '--profile', 'web', 'build', 'project'])
    assert parsed == dict(mode='plugin', profile='web', args=['build', 'project'])


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['unload', 'dependency-cycle'])
async def test_exported_remote_cannot_succeed_after_its_activation_ended(tmp_path, operation):
    source = tmp_path / 'host.py'
    source.write_text('''import asyncio
def plugin(ctx):
    control = {'entered': asyncio.Event(), 'release': asyncio.Event()}
    ctx.provide('exportControl', control)
    async def wait(args):
        control['entered'].set()
        await control['release'].wait()
        return {'settled': True}
    harness.handle('wait', wait)
plugin.inject = ['exportDependency']
''', encoding='utf-8')
    ctx = await web_context(tmp_path / 'home')
    pending = None
    try:
        provider = ctx.plugin(lambda child: child.provide('exportDependency', object()))
        await provider
        exported = ctx.plugin(python_host_source(str(source), NAME, enable_remote=True))
        await exported
        old_control = ctx.get('exportControl')
        old_remote = ctx.get(host_remote_namespace(NAME))
        pending = asyncio.ensure_future(old_remote.call('wait', None))
        await asyncio.wait_for(old_control['entered'].wait(), 5)
        if operation == 'unload':
            await exported.dispose()
        else:
            await provider.dispose()
            await provider.await_settled()
            provider = ctx.plugin(lambda child: child.provide('exportDependency', object()))
            await provider
            await exported.await_settled()
        old_control['release'].set()
        with pytest.raises(RuntimeError, match='activation ended'):
            await pending
        if operation == 'dependency-cycle':
            ctx.get('exportControl')['release'].set()
            assert await ctx.get(host_remote_namespace(NAME)).call('wait', None) == dict(settled=True)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await close_web_context(ctx)


@pytest.mark.skipif(not os.environ.get('DSH_TEST_CHROMIUM'), reason='real browser lane: set DSH_TEST_CHROMIUM')
def test_original_browser_built_creative_source_restart_upgrade_rollback(tmp_path):
    node = shutil.which('node')
    assert node
    output = tmp_path / 'python-export-browser.json'
    result = subprocess.run([node, str(ROOT / 'scripts/python_web_plugin_browser_oracle.mjs'),
        '--browser', os.environ['DSH_TEST_CHROMIUM'], '--output', str(output), '--exported', 'true'],
        cwd=str(ROOT), capture_output=True, encoding='utf-8', timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['passed'] and report['exported'] and report['python'] == '3.8.10'
    assert len(report['steps']) == 17 and len(report['replies']) == 9
    assert not report['errors'] and not report['consoleErrors'] and not report['requests']
    assert report['hostExitCode'] == 0 and not report['hostErrors']
