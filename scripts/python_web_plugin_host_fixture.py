"""Private installed-package Host used by the real original-browser journey."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.cli.plugin import run_plugin
from dsh.boot.profile import init_profile, PROFILE_TEMPLATES
from dsh.boot.profile_boot import run_profile
from scripts.build_python_web_example import build
from dsh.extensions.packaged_host import host_handler_service, host_remote_namespace

NAME = '@example/python-web-echo'
SESSION = '--session' in sys.argv
EXPORTED = '--exported' in sys.argv or SESSION
if EXPORTED:
    from scripts.python_export_client_fixture import (NAME, export_project_at, SESSION_PRESETS,
        install_session_presets, create_session_fixture)


def make_zip(project, path):
    run_plugin('web', ['pack', str(project), str(path)])


async def main():
    with tempfile.TemporaryDirectory(prefix='dsh-python-web-') as directory:
        home = Path(directory) / 'home'
        os.environ['DSH_HOME'] = str(home)
        os.environ['DSH_TELEMETRY_MODE'] = 'DISABLED'
        # Prove the installation/runtime route does not use system Node/pnpm.
        real_which = shutil.which
        shutil.which = lambda name, *args, **kwargs: None if name in ('node', 'pnpm') else real_which(name, *args, **kwargs)
        template = PROFILE_TEMPLATES['web']
        init_profile(str(home / 'profiles/web'), template['bundles'], template.get('patchReload', 'live'))
        original = Path(directory) / 'v1.zip'
        if EXPORTED:
            source_project, receipt = await export_project_at(Path(directory), placement='session' if SESSION else 'host')
            os.environ['DSH_HOME'] = str(home)
            run_plugin('web', ['build', str(source_project)])
        else:
            source_project = ROOT / 'examples/python-web-echo'
        make_zip(source_project, original)
        run_plugin('web', ['add', str(original)])
        if SESSION:
            install_session_presets(home, source_project)
        result = None
        availability = dict(gate=None, entered=False)

        def send(value):
            print('DSH_WEB_PACKAGE ' + json.dumps(value, ensure_ascii=True), flush=True)

        async def start():
            nonlocal result
            result = await run_profile(dict(profile='web', dshHome=str(home), args=['--no-open', '--port', '0'], waitForExit=False))
            if SESSION and (home / 'profiles/web/node_modules' / NAME).is_dir():
                await create_session_fixture(result['ctx'], Path(directory))
            return await snapshot()

        async def stop():
            nonlocal result
            if result is not None:
                result['shutdown'].shutdown(0)
                await result['shutdown'].wait()
                result = None

        async def snapshot():
            ctx = result['ctx']
            namespace = host_remote_namespace(NAME) if EXPORTED else 'pythonWebEcho'
            endpoint = namespace + ('/call' if EXPORTED else '/echo')
            service = ctx.get(namespace)
            session_calls = {}
            if SESSION:
                for sid in SESSION_PRESETS:
                    agent = ctx.agents.get(sid)
                    handlers = ctx.agentPresets.serviceFor(agent, host_handler_service(NAME)) if agent is not None else None
                    session_calls[sid] = (await handlers.call('snapshot', None))['calls'] if handlers is not None and handlers.active else None
                calls = session_calls['python-session-a'] if service is not None else None
            else:
                calls = (await ctx.get(host_handler_service(NAME)).call('snapshot', None))['calls'] if EXPORTED and service is not None else service.calls if service is not None else None
            return dict(url=ctx.connection.authenticated_url('http://127.0.0.1:{}'.format(ctx.webServer.port)),
                calls=calls, name=NAME, endpoint=endpoint, exported=EXPORTED, session=SESSION,
                sessionCalls=session_calls, sourceAtRoot=ctx.get(host_handler_service(NAME)) is not None,
                graph=ctx.clientModules.graph(), descriptor=ctx.typert.local.get(endpoint) is not None,
                seen=ctx.typert.local.hasSeen(endpoint), python=sys.version.split()[0])

        try:
            send(dict(ready=True, value=await start()))
            while True:
                line = await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                request = json.loads(line)
                try:
                    command = request['command']
                    if command == 'snapshot':
                        value = await snapshot()
                    elif SESSION and command == 'hold-availability':
                        native = getattr(result['ctx'].get(host_remote_namespace(NAME)), 'cordis.original')
                        original_available = native.available
                        availability['gate'] = asyncio.Event()
                        async def held_available(agent):
                            if agent.id == 'python-session-a':
                                availability['entered'] = True
                                await availability['gate'].wait()
                            return original_available(agent)
                        native.available = held_available
                        value = True
                    elif SESSION and command == 'availability-waiting':
                        value = availability['entered']
                    elif SESSION and command == 'release-availability':
                        availability['gate'].set()
                        value = True
                    elif SESSION and command == 'unload-session':
                        from dsh.presets.mount import standing_mount_for
                        ctx = result['ctx']
                        mount = standing_mount_for(ctx.agents.get('python-session-a').ctx)
                        entry = next(row for row in mount.tree.entries() if row.options.get('name') == NAME)
                        await entry.fiber.dispose()
                        await entry.fiber.await_settled()
                        value = await snapshot()
                    elif command == 'unload':
                        ctx = result['ctx']
                        entry = next(row for row in ctx.loader.entries if row.options.get('name') == NAME)
                        await entry.fiber.dispose()
                        await entry.fiber.await_settled()
                        for _ in range(20):
                            await asyncio.sleep(0)
                        value = await snapshot()
                    elif EXPORTED and command in ('rebuild-client', 'restore-client'):
                        installed = home / 'profiles/web/node_modules' / NAME
                        source = installed / 'client/source.js'
                        original_source = (source_project / 'client/source.js').read_bytes()
                        source.write_bytes(original_source + (b'\n// real HMR rebuild\n' if command == 'rebuild-client' else b''))
                        run_plugin('web', ['build', str(installed)])
                        value = await snapshot()
                    elif command in ('restart', 'upgrade', 'rollback', 'remove'):
                        await stop()
                        if command == 'upgrade':
                            project = Path(directory) / 'version-two'
                            shutil.copytree(str(source_project), str(project))
                            manifest = json.loads((project / 'package.json').read_text(encoding='utf-8'))
                            manifest['version'] = '2.0.0'
                            (project / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
                            source = project / ('python/exported/host.body.py' if EXPORTED else 'python/web_echo/plugin.py')
                            source.write_text(source.read_text(encoding='utf-8').replace("'1.0.0'", "'2.0.0'"), encoding='utf-8')
                            if EXPORTED:
                                run_plugin('web', ['build', str(project)])
                            else:
                                build(project)
                            archive = Path(directory) / 'v2.zip'
                            make_zip(project, archive)
                            run_plugin('web', ['upgrade', str(archive)])
                        elif command == 'rollback':
                            run_plugin('web', ['rollback', NAME, '1.0.0'])
                        elif command == 'remove':
                            run_plugin('web', ['remove', NAME])
                        value = await start()
                    elif command == 'shutdown':
                        send(dict(id=request['id'], ok=True, value=None))
                        break
                    else:
                        raise ValueError('unknown command')
                    send(dict(id=request['id'], ok=True, value=value))
                except Exception as error:
                    send(dict(id=request['id'], ok=False, error=str(error)))
        finally:
            await stop()
            shutil.which = real_which


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
