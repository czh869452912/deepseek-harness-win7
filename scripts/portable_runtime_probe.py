"""Release probe executed by the extracted Python, without repository imports.

The driver passes a private workspace and removes developer runtimes from PATH.
This is release verification code, not a shipped application plugin.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys


NAME = '@verification/portable-echo'
WEB_NAME = '@verification/portable-web'
SESSION = 'portable-session'


def require(value, message):
    if not value:
        raise RuntimeError(message)


def send(value):
    print('PORTABLE_PROBE ' + json.dumps(value, ensure_ascii=True), flush=True)


def identity():
    import dsh
    root = Path(sys.executable).resolve().parent
    require(sys.version_info[:3] == (3, 8, 10), 'Python version')
    require(sys.platform == 'win32' and struct.calcsize('P') == 8, 'Windows x64 runtime')
    require(Path(dsh.__file__).resolve().parent.parent == root, 'external dsh import')
    for path in sys.path:
        common = os.path.commonpath([str(root), os.path.realpath(path)])
        require(os.path.normcase(common) == os.path.normcase(str(root)), 'external Python search path: ' + path)
    for name in ('pip', 'pytest', 'quickjs'):
        require(importlib.util.find_spec(name) is None, 'development/JS dependency bundled: ' + name)
    for name in ('python', 'node', 'pnpm'):
        resolved = shutil.which(name)
        require(resolved is None or Path(resolved).resolve().parent == root, 'external runtime available: ' + name)
    sys.dont_write_bytecode = True
    return dict(version=list(sys.version_info[:3]), platform=sys.platform,
                executable=str(sys.executable), paths=list(sys.path), dsh=dsh.__file__)


def project(workspace, version, prefix):
    root = workspace / ('plugin-' + version)
    source = root / 'python' / 'echo'
    source.mkdir(parents=True)
    (source / '__init__.py').write_text('', encoding='utf-8')
    (source / 'plugin.py').write_text('''from dsh.plugin_api import Plugin
import portable_helper
class EchoPlugin(Plugin):
    name = 'portable-echo'
    inject = ['tools']
    def apply(self, ctx, config):
        async def execute(args, execution):
            return portable_helper.format(args['text'])
        ctx.tools.register({'name': 'portable_echo', 'description': 'Private release probe',
            'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']},
            'execute': execute, 'output': {'schema': {'type': 'string'},
                'render': lambda args, value: [{'type': 'text', 'text': value}]}})
''', encoding='utf-8')
    (root / 'cordis.patch.yml').write_text("- insert:\n    - id: portable-echo\n      name: '@verification/portable-echo'\n", encoding='utf-8')
    (root / 'LICENSE').write_text('Private verification fixture, no redistribution grant.\n', encoding='utf-8')
    (root / 'README.md').write_text('Private Portable plugin and transitive dependency probe.\n', encoding='utf-8')
    rows = []
    for distribution, module, requires, code in (
        ('portable-helper', 'portable_helper', ['portable-leaf==' + version],
         'import portable_leaf\ncount = 0\ndef format(text):\n    global count\n    count += 1\n    return portable_leaf.PREFIX + text + ":" + str(count)\n'),
        ('portable-leaf', 'portable_leaf', [], 'PREFIX = ' + repr(prefix) + '\n'),
    ):
        vendor = root / 'vendor' / distribution
        package = vendor / module
        package.mkdir(parents=True)
        (package / '__init__.py').write_text(code, encoding='utf-8')
        (vendor / 'LICENSE').write_text('Private verification dependency.\n', encoding='utf-8')
        files = {p.relative_to(vendor).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in vendor.rglob('*') if p.is_file()}
        rows.append(dict(name=distribution, version=version, sourceRoot='vendor/' + distribution,
                         imports=[module], requires=requires, files=files, origin='private-release-probe'))
    manifest = dict(name=NAME, version=version, license='UNLICENSED', dsh=dict(
        bundle=dict(patch='cordis.patch.yml'),
        python=dict(apiVersion=1, sourceRoot='python', entry='echo.plugin:EchoPlugin',
                    minPythonVersion=[3, 8, 10], minHostVersion=[0, 1, 0], dependencies=['portable-helper==' + version]),
        pythonDependencies=dict(formatVersion=1, python=[3, 8, 10], abi='none', platform='any', packages=rows)))
    manifest['dsh']['release'] = dict(formatVersion=1, files=sorted(
        ['package.json'] + [p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()]))
    (root / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    return root


async def close(result):
    result['shutdown'].shutdown(0)
    await result['shutdown'].wait()


async def journey(workspace, home):
    from apps.cli.plugin import run_plugin
    from dsh.boot.profile import init_profile
    from dsh.boot.profile_boot import run_profile
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.tools import ToolExecutionInput
    report = dict(identity=identity(), steps=[])
    root = Path(sys.executable).parent
    for profile in ('minimal', 'standard', 'creative', 'web', 'headless'):
        result = subprocess.run([sys.executable, '-I', str(root / 'dsh.py'), '--profile', profile, '--dump-config'],
                                cwd=str(workspace), capture_output=True, encoding='utf-8', timeout=60)
        require(result.returncode == 0 and result.stdout.strip(), 'profile dump failed: ' + profile + ': ' + result.stderr)
        report['steps'].append('dump-' + profile)
    directory = home / 'profiles' / 'portable-probe'
    init_profile(str(directory), [], 'startup')
    (directory / 'cordis.patch.yml').write_text("- insert:\n    - id: tools\n      name: '@deepseek-ai/dsh-tools'\n", encoding='utf-8')
    first = project(workspace, '1.0.0', '原生:')
    newer = project(workspace, '2.0.0', '升级:')
    archive = workspace / 'plugin.zip'
    require(run_plugin('portable-probe', ['pack', str(first), str(archive)]) == 0, 'pack failed')
    require(run_plugin('portable-probe', ['add', str(archive)]) == 0, 'install failed')
    async def execute(expected):
        result = await run_profile(dict(profile='portable-probe', dshHome=str(home), args=[], waitForExit=False))
        try:
            value = await result['ctx'].tools.execute(ToolExecutionInput('portable-echo', 'portable_echo',
                dict(text='中文 portable'), signal=NEVER_ABORTED))
            require(not value.is_error and value.value == expected + '中文 portable:1', 'actual plugin tool result: ' + repr(value.value))
            import portable_helper
            require('dsh-python-dependencies-' in portable_helper.__file__, 'dependency lease not used')
        finally:
            await close(result)
        require('portable_helper' not in sys.modules and 'portable_leaf' not in sys.modules, 'dependency modules survived shutdown')
    await execute('原生:')
    await execute('原生:')
    report['steps'].extend(['pack-install-transitive-dependencies', 'tool-execute-restart-module-cleanup'])
    require(run_plugin('portable-probe', ['upgrade', str(newer)]) == 0, 'upgrade failed')
    await execute('升级:')
    require(run_plugin('portable-probe', ['rollback', NAME, '1.0.0']) == 0, 'rollback failed')
    await execute('原生:')
    require(run_plugin('portable-probe', ['remove', NAME]) == 0, 'remove failed')
    require(not (directory / 'node_modules' / NAME).exists(), 'installed source survived remove')
    report['steps'].extend(['upgrade-real-tool', 'rollback-real-tool', 'remove-installed-source'])

    # Generate a real creative-mode project, build its original-evaluator Client,
    # then pack/install with the extracted application's own implementations.
    author = await run_profile(dict(profile='web', dshHome=str(home), args=['--no-open', '--port', '0'], waitForExit=False))
    try:
        ctx = author['ctx']
        await ctx.sessionController.create(dict(sessionId='portable-author', cwd=str(workspace), agentPreset='cordis'))
        agent = ctx.agents.get('portable-author')
        receipt = ctx.dynamicCordisRunner.define(dict(sessionId=agent.id, plugin=dict(kind='new', idPrefix='port'),
            name='Portable proof', purpose='Original browser to extracted Python', code=dict(
                host='def plugin(ctx):\n    harness.handle("echo", lambda args: {"value": args, "runtime": "Python 3.8.10"})\n',
                client='''styles.insert('[data-portable-panel] {position: fixed; top: 20px; left: 800px; z-index: 999;}');
return {inject: ['slots'], apply(ctx) {
  function Panel() {
    const [result, setResult] = React.useState('ready');
    return React.createElement('div', {'data-portable-panel': true},
      React.createElement('button', {'data-portable-call': true, onClick: async () => {
        try {setResult(JSON.stringify({ok: true, value: await host.call('echo', {text: '中文 portable', nested: [null, true, 42]})}));}
        catch (error) {setResult(String(error));}
      }}, 'Call Python'), React.createElement('output', {'data-portable-result': true}, result));
  }
  ctx.slots.inject('shell.overlay', () => ctx.slots.register({name: 'shell.overlay', id: 'portable-proof'}, Panel));
}}''')))
        exported = await ctx.tools.execute(ToolExecutionInput('portable-export', 'cordis_export', dict(
            pluginId=receipt['pluginId'], packageId=receipt['packageId'], directory='web-project',
            name=WEB_NAME, version='1.0.0', placement='host', isolateServices=[],
            license='UNLICENSED', licenseText='Private release verification fixture.\n'), agent=agent, signal=NEVER_ABORTED))
        require(not exported.is_error, 'creative export: ' + repr(exported.error))
    finally:
        await close(author)
    web_project = workspace / 'web-project'
    require(run_plugin('web', ['build', str(web_project)]) == 0, 'native client build')
    web_archive = workspace / 'web-plugin.zip'
    require(run_plugin('web', ['pack', str(web_project), str(web_archive)]) == 0, 'web pack')
    require(run_plugin('web', ['add', str(web_archive)]) == 0, 'web install')
    report['steps'].append('creative-export-native-build-pack-install')
    web = await boot_web(home)
    try:
        ctx = web['ctx']
        await ctx.sessionController.create(dict(sessionId=SESSION, cwd=str(workspace), agentPreset='minimal'))
        agent = ctx.agents.get(SESSION)
        agent.session.append_user_message('中文 portable prepared Session fixture')
        agent.session.append('turn/start', dict(turn=1))
        agent.session.append('turn/end', dict(turn=1, reason=dict(kind='completed')))
        await ctx.sessionController.rename(dict(sessionId=SESSION, title=SESSION))
        await agent.session.flush()
    finally:
        await close(web)
    restarted = await boot_web(home)
    try:
        ctx = restarted['ctx']
        rows = await ctx.sessionQuery.listSessions()
        require(any(row['header'].id == SESSION and row['persisted'] and not row['live'] for row in rows), 'cold session missing')
        surface = await ctx.sessionQuery.readSurface(SESSION)
        # Public readSurface proves actual persisted records can be replayed.
        require(any(event['type'] == 'user/message' for event in surface['events']), 'cold user record missing')
        observation = await ctx.sessionQuery.observeSession(SESSION)
        try:
            require(observation.projections['values']['title'] == SESSION, 'persisted title replay missing')
        finally:
            observation.dispose()
    finally:
        await close(restarted)
    report['steps'].extend(['web-real-boot-session-flush', 'cold-session-restart-read-surface'])
    return report


async def boot_web(home):
    from dsh.boot.profile_boot import run_profile
    return await run_profile(dict(profile='web', dshHome=str(home), args=['--no-open', '--port', '0'], waitForExit=False))


async def serve(home):
    from dsh.extensions.packaged_host import host_remote_namespace
    report = identity()
    result = await boot_web(home)
    try:
        ctx = result['ctx']
        namespace = host_remote_namespace(WEB_NAME)
        require(ctx.typert.local.get(namespace + '/call') is not None, 'installed Remote descriptor missing')
        send(dict(ready=True, value=dict(identity=report,
            url=ctx.connection.authenticated_url('http://127.0.0.1:{}'.format(ctx.webServer.port)),
            endpoint=namespace + '/call', session=SESSION, graph=ctx.clientModules.graph())))
        while True:
            line = await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
            if not line or json.loads(line).get('command') == 'stop':
                break
    finally:
        await close(result)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--serve', action='store_true')
    options = parser.parse_args()
    workspace = Path(options.workspace).resolve()
    home = workspace / 'home'
    os.environ['DSH_HOME'] = str(home)
    os.environ['DSH_TELEMETRY_MODE'] = 'DISABLED'
    if options.serve:
        asyncio.run(serve(home))
    else:
        send(dict(result='passed', value=asyncio.run(journey(workspace, home))))


if __name__ == '__main__':
    main()
