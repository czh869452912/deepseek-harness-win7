"""Private browser fixture executing the shipped Win7 authoring examples."""
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
from dsh.boot.profile_boot import run_profile
from dsh.extensions.packaged_host import host_handler_service
from scripts.python_export_client_fixture import export_project_at, NAME

EXAMPLES = ROOT / 'packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/examples'


async def main():
    with tempfile.TemporaryDirectory(prefix='dsh-guide-browser-') as folder:
        workspace = Path(folder)
        project, _ = await export_project_at(workspace,
            host_source=(EXAMPLES / 'counter.host.py').read_text(encoding='utf-8'),
            client_source=(EXAMPLES / 'echo.overlay.client.js').read_text(encoding='utf-8'))
        home = workspace / 'installed-home'
        os.environ['DSH_HOME'] = str(home)
        os.environ['DSH_TELEMETRY_MODE'] = 'DISABLED'
        real_which = shutil.which
        shutil.which = lambda name, *args, **kwargs: None if name in ('node', 'pnpm', 'pip') else real_which(name, *args, **kwargs)
        result = None

        def package(version):
            archive = workspace / ('guide-' + version + '.zip')
            run_plugin('web', ['build', str(project)])
            run_plugin('web', ['pack', str(project), str(archive)])
            return archive

        first = package('1.0.0')
        run_plugin('web', ['add', str(first)])

        async def start():
            nonlocal result
            result = await run_profile(dict(profile='web', dshHome=str(home),
                args=['--no-open', '--port', '0'], waitForExit=False))
            server = result['ctx'].get('webServer')
            url = result['ctx'].get('connection').authenticated_url('http://127.0.0.1:' + str(server.port))
            return dict(url=url, python='.'.join(map(str, sys.version_info[:3])))

        async def stop():
            nonlocal result
            if result is not None:
                result['shutdown'].shutdown(0)
                await result['shutdown'].wait()
                result = None

        def send(value):
            print('WIN7_GUIDE ' + json.dumps(value, ensure_ascii=True), flush=True)

        try:
            send(await start())
            while True:
                line = await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                request = json.loads(line)
                try:
                    command = request['command']
                    if command == 'address':
                        server = result['ctx'].get('webServer')
                        value = dict(url=result['ctx'].get('connection').authenticated_url('http://127.0.0.1:' + str(server.port)))
                    elif command == 'restart':
                        await stop()
                        value = await start()
                    elif command == 'upgrade':
                        await stop()
                        path = project / 'package.json'
                        manifest = json.loads(path.read_text(encoding='utf-8'))
                        manifest['version'] = '1.1.0'
                        path.write_text(json.dumps(manifest), encoding='utf-8')
                        source = project / 'python/exported/host.body.py'
                        source.write_text(source.read_text(encoding='utf-8').replace("'text': args['text']", "'text': args['text'] + ' v2'"), encoding='utf-8')
                        run_plugin('web', ['upgrade', str(package('1.1.0'))])
                        value = await start()
                    elif command == 'rollback':
                        await stop()
                        run_plugin('web', ['rollback', NAME, '1.0.0'])
                        value = await start()
                    elif command == 'unload':
                        ctx = result['ctx']
                        retained = ctx.get(host_handler_service(NAME))
                        entry = next(row for row in ctx.get('loader').entries if row.options.get('name') == NAME)
                        await entry.fiber.dispose()
                        await entry.fiber.await_settled()
                        try:
                            await retained.call('echo', dict(text='stale'))
                            revoked = False
                        except RuntimeError as error:
                            revoked = 'unloaded' in str(error)
                        value = dict(withdrawn=ctx.get(host_handler_service(NAME)) is None, retainedRpcRevoked=revoked)
                    elif command == 'stop':
                        await stop()
                        send(dict(id=request['id'], value=dict(stopped=True)))
                        break
                    else:
                        raise ValueError('unknown fixture command')
                    send(dict(id=request['id'], value=value))
                except Exception as error:
                    send(dict(id=request['id'], error=str(error)))
        finally:
            await stop()


if __name__ == '__main__':
    asyncio.run(main())
