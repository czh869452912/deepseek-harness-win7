"""Owned source export through real Tools, install, isolated presets and restart."""
from dsh.core.system_prompt import SystemPrompt as SourceToolsPrompt
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import zipfile

import pytest
import yaml

from apps.cli import plugin as cli
from apps.cli.args import parse_dsh_args
from canonical_web_fixture import web_context, close_web_context
from dsh.boot.python_package import validate_sources
from dsh.boot.python_plugin_export import export_project, project_files
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.fs.fs_local import FsService
from dsh.fs.fs_sandbox import SandboxedFileSystem
from dsh.extensions.packaged_host import host_handler_service
from test_python_plugin_distribution import profile, boot, close

NAME = '@author/export-probe'
SOURCE = '''counter = [0]
def plugin(ctx):
    def count(args, execution):
        counter[0] += 1
        return counter[0]
    tool = harness.defineTool({'name': 'export_counter', 'description': 'Count calls', 'parameters': {}, 'output': {'schema': {'type': 'integer'}, 'render': lambda args, value: [{'type': 'text', 'text': str(value)}]}, 'execute': count})
    harness.registerTool(ctx, tool)
    ctx.provide('exportValue', 'first')
    harness.handle('read', lambda args: {'value': ctx.get('exportValue'), 'calls': counter[0]})
plugin.inject = ['tools']
'''


def arguments(receipt, directory='project', placement='host'):
    return dict(pluginId=receipt['pluginId'], packageId=receipt['packageId'], directory=directory,
        name=NAME, version='1.0.0', placement=placement, isolateServices=['exportValue'],
        license='UNLICENSED', licenseText='Test source. Redistribution requires author permission.\n')


async def actual_export(ctx, agent, args):
    tools = ctx.get('tools')
    return await tools.execute(ToolExecutionInput('export-call', 'cordis_export', args,
        agent=agent, signal=NEVER_ABORTED))


async def count(ctx, agent=None):
    result = await ctx.get('tools').execute(ToolExecutionInput('counter-call', 'export_counter', {},
        agent=agent, signal=NEVER_ABORTED))
    assert not result.is_error, result.error
    return result.value


@pytest.mark.asyncio
@pytest.mark.parametrize('container', ['directory', 'zip'])
async def test_exact_old_version_export_installs_unloads_restarts_and_rolls_back(profile, tmp_path, container):
    home, _ = profile
    author = await web_context(tmp_path / 'author-home')
    try:
        await author.get('sessionController').create(dict(sessionId='export-owner', cwd=str(tmp_path), agentPreset='cordis'))
        agent = author.get('agents').get('export-owner')
        runner = author.get('dynamicCordisRunner')
        first = runner.define(dict(sessionId=agent.id, plugin=dict(kind='new', idPrefix='probe'),
            name='First', purpose='Export first version', code=dict(host=SOURCE)))
        runner.define(dict(sessionId=agent.id, plugin=dict(kind='existing', pluginId=first['pluginId']),
            name='Second', purpose='Different latest version', code=dict(host=SOURCE.replace("'first'", "'latest'"))))
        result = await actual_export(author, agent, arguments(first))
        assert not result.is_error, result.error
        assert result.value['requiresClientBuild'] is False
        assert result.content[0]['type'] == 'text'
    finally:
        await close_web_context(author)
    project = tmp_path / 'project'
    origin = json.loads((project / 'dsh-export.json').read_text(encoding='utf-8'))
    assert origin['sourceSha256'] == dict(host=hashlib.sha256(SOURCE.encode('utf-8')).hexdigest())
    assert origin['packageId'] == first['packageId']
    assert 'agentId' not in origin and str(tmp_path) not in json.dumps(origin)
    assert (project / 'python/exported/host.body.py').read_bytes() == SOURCE.encode('utf-8')
    source = project
    if container == 'zip':
        (project / '.env').write_text('SECRET=private', encoding='utf-8')
        (project / '.venv').mkdir()
        (project / '.venv/python.exe').write_bytes(b'not a release dependency')
        source = tmp_path / 'plugin.zip'
        assert cli.run_plugin('python-test', ['pack', str(project), str(source)]) == 0
        with zipfile.ZipFile(str(source)) as archive:
            assert archive.read('python/exported/host.body.py') == SOURCE.encode('utf-8')
            assert '.env' not in archive.namelist()
            assert '.venv/python.exe' not in archive.namelist()
    assert cli.run_plugin('python-test', ['add', str(source)]) == 0
    installed = profile[1] / 'node_modules/@author/export-probe'
    assert not (installed / '.env').exists()
    assert not (installed / '.venv').exists()
    mounted = await boot(home)
    try:
        ctx = mounted['ctx']
        assert await count(ctx) == 1
        handlers = ctx.get(host_handler_service(NAME))
        assert await handlers.call('read', {}) == dict(value='first', calls=1)
        row = next(entry for entry in ctx.loader.entries if entry.options.get('name') == NAME)
        await row.fiber.dispose()
        await row.fiber.await_settled()
        assert ctx.get('exportValue') is None
        with pytest.raises(RuntimeError, match='unloaded'):
            await handlers.call('read', {})
        missing = await ctx.get('tools').execute(ToolExecutionInput('gone', 'export_counter', {}, signal=NEVER_ABORTED))
        assert missing.is_error and missing.error['info']['code'] == 'UNKNOWN_TOOL'
    finally:
        await close(mounted)
    restarted = await boot(home)
    try:
        assert await count(restarted['ctx']) == 1
    finally:
        await close(restarted)
    manifest = json.loads((project / 'package.json').read_text(encoding='utf-8'))
    manifest['version'] = '2.0.0'
    (project / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    (project / 'python/exported/host.body.py').write_text(SOURCE.replace("'first'", "'upgrade'"), encoding='utf-8')
    assert cli.run_plugin('python-test', ['upgrade', str(project)]) == 0
    assert not (installed / '.env').exists()
    assert not (installed / '.venv').exists()
    upgraded = await boot(home)
    try:
        assert upgraded['ctx'].get('exportValue') == 'upgrade'
    finally:
        await close(upgraded)
    assert cli.run_plugin('python-test', ['rollback', NAME, '1.0.0']) == 0
    rolled = await boot(home)
    try:
        assert rolled['ctx'].get('exportValue') == 'first'
        assert await count(rolled['ctx']) == 1
    finally:
        await close(rolled)


def write_project(directory, files):
    for relative, text in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8', newline='') as stream:
            stream.write(text)


@pytest.mark.asyncio
async def test_session_project_installs_without_host_tools_and_uses_independent_presets(tmp_path):
    home = tmp_path / 'home'
    project = tmp_path / 'session-project'
    write_project(project, project_files(dict(packageId='pkg-1', name='Test', purpose='Session ownership', code=dict(host=SOURCE)),
        'probe-1', NAME, '1.0.0', 'session', ['exportValue'], 'UNLICENSED', 'Test source\n'))
    seed = await web_context(home)
    await close_web_context(seed)
    # Install into the actual Web profile, while it is stopped.
    from pytest import MonkeyPatch
    env = MonkeyPatch()
    env.setenv('DSH_HOME', str(home))
    try:
        assert cli.run_plugin('web', ['add', str(project)]) == 0
    finally:
        env.undo()
    original = Path(__file__).resolve().parents[1] / 'packages/preset/agent-presets/presets/minimal/agent.cordis.yml'
    # Preserve shipped !!js expressions rather than changing browser or boot.
    with original.open(encoding='utf-8') as stream:
        text = stream.read()
    fragment = json.loads((project / 'preset.fragment.yml').read_text(encoding='utf-8'))
    for name in ('exported-a', 'exported-b'):
        preset = home / '.agent-presets' / name
        preset.mkdir(parents=True)
        (preset / 'agent.cordis.yml').write_text(text + '\n' + yaml.safe_dump(fragment, sort_keys=False), encoding='utf-8')
    for restart in range(2):
        ctx = await web_context(home)
        try:
            assert ctx.get(host_handler_service(NAME)) is None
            assert 'export_counter' not in {tool.name for tool in ctx.get('tools').list_tools()}
            for sid, selected in (('export-a', 'exported-a'), ('export-b', 'exported-b'), ('shared-a', 'exported-a'), ('plain', 'minimal')):
                await ctx.get('sessionController').create(dict(sessionId=sid + str(restart), cwd=str(tmp_path), agentPreset=selected))
            a = ctx.get('agents').get('export-a' + str(restart))
            b = ctx.get('agents').get('export-b' + str(restart))
            assert await count(ctx, a) == 1
            assert await count(ctx, a) == 2
            assert await count(ctx, b) == 1
            assert await count(ctx, ctx.get('agents').get('shared-a' + str(restart))) == 3
            plain = ctx.get('agents').get('plain' + str(restart))
            assert 'export_counter' not in {tool.name for tool in ctx.get('tools').list_tools(scope=plain.ctx)}
            from dsh.presets.mount import service_for_agent
            assert service_for_agent(ctx, a, host_handler_service(NAME)) is not service_for_agent(ctx, b, host_handler_service(NAME))
            assert service_for_agent(ctx, a, 'exportValue') == service_for_agent(ctx, b, 'exportValue') == 'first'
            assert ctx.get('exportValue') is None
        finally:
            await close_web_context(ctx)


@pytest.mark.asyncio
async def test_foreign_owner_and_client_export_are_explicit(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        for sid in ('owner', 'foreign'):
            await ctx.get('sessionController').create(dict(sessionId=sid, cwd=str(tmp_path), agentPreset='cordis'))
        agent, foreign = [ctx.get('agents').get(sid) for sid in ('owner', 'foreign')]
        receipt = ctx.get('dynamicCordisRunner').define(dict(sessionId=agent.id, plugin=dict(kind='new', idPrefix='probe'),
            name='Both', purpose='Preserve both halves', code=dict(host=SOURCE, client='return function(ctx) {}')))
        denied = await actual_export(ctx, foreign, arguments(receipt, 'foreign-project'))
        assert denied.is_error and not (tmp_path / 'foreign-project').exists()
        exported = await actual_export(ctx, agent, arguments(receipt))
        assert not exported.is_error, exported.error
        assert exported.value['requiresClientBuild']
        project = tmp_path / 'project'
        assert (project / 'client/source.js').read_text(encoding='utf-8') == 'return function(ctx) {}'
        with pytest.raises(ValueError, match='Client source requires a build'):
            validate_sources(str(project))
        with pytest.raises(ValueError, match='Client source requires a build'):
            cli.run_plugin('web', ['pack', str(project), str(tmp_path / 'client.zip')])
        assert not (tmp_path / 'client.zip').exists()
        repeated = await actual_export(ctx, agent, arguments(receipt))
        assert repeated.is_error and 'already exist' in repeated.error['message']
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['readonly', 'outside', 'abort-before', 'abort-mid', 'collision'])
async def test_export_respects_fs_policy_cancellation_and_commit_point(tmp_path, failure):
    controller = AbortController()
    package = dict(packageId='pkg-1', name='Test', purpose='FS policy', code=dict(host=SOURCE))
    agent = NS(id='owner', session=NS(header=NS(cwd=str(tmp_path))))
    fs = FsService(cwd=str(tmp_path))
    if failure == 'readonly':
        policy = NS(defaultMode='read-only', resolve=lambda *_: dict(mode='read-only', writableRoots=[]))
        fs = SandboxedFileSystem(NS(sandboxPolicy=policy), {})
    else:
        policy = None
    runner = NS(inspectPackage=lambda *_: package)
    ctx = NS(get=lambda name: dict(dynamicCordisRunner=runner, fs=fs, sandboxPolicy=policy).get(name))
    args = arguments(dict(pluginId='probe-1', packageId='pkg-1'))
    if failure == 'outside':
        args['directory'] = '../outside'
    if failure == 'abort-before':
        controller.abort(ValueError('stop export'))
    if failure in ('abort-mid', 'collision'):
        write = fs.writeText
        calls = []
        async def intercepted(target, text, *positional, **keywords):
            calls.append(target.displayPath)
            if len(calls) == 2:
                if failure == 'abort-mid':
                    controller.abort(ValueError('stop export'))
                else:
                    Path(target.displayPath).write_text('foreign content', encoding='utf-8')
            return await write(target, text, *positional, **keywords)
        fs.writeText = intercepted
    with pytest.raises(Exception):
        await export_project(ctx, args, NS(agent=agent, signal=controller.signal))
    assert not (tmp_path / 'project/package.json').exists()
    if failure in ('readonly', 'abort-before', 'outside'):
        assert not (tmp_path / 'project').exists()
    else:
        assert (tmp_path / 'project/dsh-export.json').exists()
        with pytest.raises(FileNotFoundError):
            validate_sources(str(tmp_path / 'project'))


def test_pack_cli_no_overwrite_output_inside_or_missing_arguments(profile, tmp_path):
    project = tmp_path / 'project'
    write_project(project, project_files(dict(packageId='pkg-1', name='Test', purpose='Pack', code=dict(host=SOURCE)),
        'probe-1', NAME, '1.0.0', 'host', [], 'UNLICENSED', 'Test source\n'))
    args = parse_dsh_args(['plugin', '--profile', 'python-test', 'pack', str(project), str(tmp_path / 'pack.zip')])
    assert cli.run_plugin(args['profile'], args['args']) == 0
    before = (tmp_path / 'pack.zip').read_bytes()
    with pytest.raises(FileExistsError):
        cli.run_plugin('python-test', ['pack', str(project), str(tmp_path / 'pack.zip')])
    assert (tmp_path / 'pack.zip').read_bytes() == before
    with pytest.raises(ValueError, match='outside'):
        cli.run_plugin('python-test', ['pack', str(project), str(project / 'pack.zip')])
    with pytest.raises(ValueError, match='use pack'):
        cli.run_plugin('python-test', ['pack', str(project)])


@pytest.mark.asyncio
async def test_exported_sdk_dependency_loss_revokes_handlers_and_tools(tmp_path):
    from dsh.cordis.context import Context
    from dsh.core.tools import ToolsPlugin
    from dsh.extensions.packaged_host import python_host_source
    source = tmp_path / 'source.py'
    source.write_text(SOURCE.replace("['tools']", "['tools', 'requiredService']"), encoding='utf-8')
    ctx = Context()
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin())
    provider = ctx.plugin(dict(name='required-provider', apply=lambda child: child.provide('requiredService', object())))
    await provider
    mounted = ctx.plugin(python_host_source(str(source), NAME))
    await mounted
    handlers = ctx.get(host_handler_service(NAME))
    assert await count(ctx) == 1
    await provider.dispose()
    await provider.await_settled()
    # Dependency loss retires the child before any retained handler can execute.
    for fiber in ctx.registry.list_fibers():
        await fiber.await_settled()
    assert ctx.get(host_handler_service(NAME)) is None
    with pytest.raises(RuntimeError, match='unloaded'):
        await handlers.call('read', {})
    assert 'export_counter' not in {tool.name for tool in ctx.tools.list_tools()}
    await mounted.dispose()
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_missing_dependency_is_pending_without_false_publication(tmp_path):
    from dsh.cordis.context import Context
    from dsh.cordis.fiber import FiberState
    from dsh.extensions.packaged_host import python_host_source
    source = tmp_path / 'source.py'
    source.write_text("def plugin(ctx):\n    ctx.provide('neverPublished', True)\nplugin.inject = ['missingProvider']\n", encoding='utf-8')
    ctx = Context()
    fiber = ctx.plugin(python_host_source(str(source), NAME))
    try:
        await fiber
        assert fiber.state == FiberState.PENDING
        assert ctx.get('neverPublished') is None
        assert ctx.get(host_handler_service(NAME)) is None
        provider = ctx.plugin(lambda child: child.provide('missingProvider', object()))
        await provider
        await fiber.await_settled()
        assert fiber.state == FiberState.ACTIVE
        assert ctx.get('neverPublished') is True
        await provider.dispose()
        await fiber.await_settled()
        assert ctx.get('neverPublished') is None
        assert ctx.get(host_handler_service(NAME)) is None
    finally:
        await fiber.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_canonical_boot_rejects_pending_export_without_evaluating_globals(profile, tmp_path):
    home, directory = profile
    marker = tmp_path / 'must-not-run'
    source = ("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('ran', encoding='utf-8')\n"
              "def plugin(ctx):\n    ctx.provide('neverPublished', True)\nplugin.inject = ['missingProvider']\n")
    project = tmp_path / 'pending-project'
    write_project(project, project_files(dict(packageId='pkg-pending', name='Pending', purpose='Dependency readiness',
        code=dict(host=source)), 'probe-pending', NAME, '1.0.0', 'host', [], 'UNLICENSED', 'Test source\n'))
    assert cli.run_plugin('python-test', ['add', str(project)]) == 0
    with pytest.raises(Exception, match='pending.*missingProvider'):
        await boot(home)
    assert not marker.exists()
    assert cli.run_plugin('python-test', ['remove', NAME]) == 0
    assert not (directory / 'node_modules' / NAME).exists()


@pytest.mark.asyncio
async def test_canonical_export_dependency_epochs_preserve_owned_globals_and_handlers(profile, tmp_path):
    home, directory = profile
    project = tmp_path / 'epochs-project'
    write_project(project, project_files(dict(packageId='pkg-epochs', name='Epochs', purpose='Loader dependency ownership',
        code=dict(host=SOURCE)), 'probe-epochs', NAME, '1.0.0', 'host', [], 'UNLICENSED', 'Test source\n'))
    assert cli.run_plugin('python-test', ['add', str(project)]) == 0
    mounted = await boot(home)
    ctx = mounted['ctx']
    try:
        handlers = ctx.get(host_handler_service(NAME))
        assert await count(ctx) == 1
        prompt = next(entry for entry in ctx.loader.entries if entry.options.get('id') == 'system-prompt')
        await prompt.update({'disabled': True})
        for iteration in range(3):
            for fiber in ctx.registry.list_fibers():
                await fiber.await_settled()
            await asyncio.sleep(0)
        assert ctx.get('tools') is None
        assert ctx.get(host_handler_service(NAME)) is None
        assert not handlers.closed
        with pytest.raises(RuntimeError, match='unloaded'):
            await handlers.call('read', {})
        await prompt.update({'disabled': False})
        await ctx.loader.await_tasks()
        for iteration in range(3):
            for fiber in ctx.registry.list_fibers():
                await fiber.await_settled()
            await asyncio.sleep(0)
        assert ctx.get('tools') is not None, [(entry.options.get('id'), entry.fiber.state if entry.fiber else None,
            str(entry.fiber._error) if entry.fiber else None) for entry in ctx.loader.entries]
        assert ctx.get(host_handler_service(NAME)) is handlers
        assert await count(ctx) == 2
        assert await handlers.call('read', {}) == dict(value='first', calls=2)
    finally:
        await close(mounted)
    assert handlers.closed
    assert cli.run_plugin('python-test', ['remove', NAME]) == 0
    assert not (directory / 'node_modules' / NAME).exists()


@pytest.mark.parametrize('mutation', ['missing-source', 'missing-license', 'duplicate', 'escape'])
def test_pack_rejects_invalid_release_list_before_creating_zip(tmp_path, mutation):
    project = tmp_path / 'project'
    write_project(project, project_files(dict(packageId='pkg-1', name='Test', purpose='Pack', code=dict(host=SOURCE)),
        'probe-1', NAME, '1.0.0', 'host', [], 'UNLICENSED', 'Test source\n'))
    manifest = json.loads((project / 'package.json').read_text(encoding='utf-8'))
    files = manifest['dsh']['sourceExport']['files']
    if mutation == 'missing-source':
        files.remove('python/exported/host.body.py')
    elif mutation == 'missing-license':
        files.remove('LICENSE')
    elif mutation == 'duplicate':
        files.append(files[0])
    else:
        files.append('../outside')
    (project / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        cli.run_plugin('web', ['pack', str(project), str(tmp_path / 'bad.zip')])
    assert not (tmp_path / 'bad.zip').exists()


def test_zip_extra_private_files_are_rejected_without_changing_profile(profile, tmp_path):
    project = tmp_path / 'project'
    write_project(project, project_files(dict(packageId='pkg-1', name='Test', purpose='Pack', code=dict(host=SOURCE)),
        'probe-1', NAME, '1.0.0', 'host', [], 'UNLICENSED', 'Test source\n'))
    archive_path = tmp_path / 'bad.zip'
    cli.run_plugin('python-test', ['pack', str(project), str(archive_path)])
    with zipfile.ZipFile(str(archive_path), 'a') as archive:
        archive.writestr('.env', 'SECRET=not-a-release-file')
    before = (profile[1] / 'package.json').read_bytes()
    with pytest.raises(ValueError, match='outside its explicit release list'):
        cli.run_plugin('python-test', ['add', str(archive_path)])
    assert (profile[1] / 'package.json').read_bytes() == before
    assert not (profile[1] / 'node_modules/@author/export-probe').exists()


@pytest.mark.asyncio
async def test_source_export_cannot_write_into_installation_owned_presets():
    root = Path(__file__).resolve().parents[1]
    agent = NS(id='owner', session=NS(header=NS(cwd=str(root))))
    package = dict(packageId='pkg-1', name='Test', purpose='Protected presets', code=dict(host=SOURCE))
    fs = FsService(cwd=str(root))
    ctx = NS(get=lambda name: dict(dynamicCordisRunner=NS(inspectPackage=lambda *_: package), fs=fs).get(name))
    args = arguments(dict(pluginId='probe-1', packageId='pkg-1'), 'dsh/presets/export-must-not-create')
    with pytest.raises(ValueError, match='installation-owned'):
        await export_project(ctx, args, NS(agent=agent, signal=NEVER_ABORTED))
    assert not (root / args['directory']).exists()


@pytest.mark.asyncio
async def test_failed_exported_plugin_reverses_partial_registrations(tmp_path):
    from dsh.cordis.context import Context
    from dsh.core.tools import ToolsPlugin
    from dsh.extensions.packaged_host import python_host_source
    source = tmp_path / 'source.py'
    source.write_text(SOURCE.replace("harness.handle('read'", "raise ValueError('failed activation')\n    harness.handle('read'"), encoding='utf-8')
    ctx = Context()
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin())
    fiber = ctx.plugin(python_host_source(str(source), NAME))
    with pytest.raises(Exception, match='failed activation'):
        await fiber
    assert ctx.get('exportValue') is None
    assert ctx.get(host_handler_service(NAME)) is None
    assert 'export_counter' not in {tool.name for tool in ctx.tools.list_tools()}
    await fiber.dispose()
    await ctx.fiber.dispose()
