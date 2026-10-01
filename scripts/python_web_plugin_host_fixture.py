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

NAME = '@example/python-web-echo'


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
        make_zip(ROOT / 'examples/python-web-echo', original)
        run_plugin('web', ['add', str(original)])
        result = None

        def send(value):
            print('DSH_WEB_PACKAGE ' + json.dumps(value, ensure_ascii=True), flush=True)

        async def start():
            nonlocal result
            result = await run_profile(dict(profile='web', dshHome=str(home), args=['--no-open', '--port', '0'], waitForExit=False))
            return snapshot()

        async def stop():
            nonlocal result
            if result is not None:
                result['shutdown'].shutdown(0)
                await result['shutdown'].wait()
                result = None

        def snapshot():
            ctx = result['ctx']
            service = ctx.get('pythonWebEcho')
            return dict(url=ctx.connection.authenticated_url('http://127.0.0.1:{}'.format(ctx.webServer.port)),
                calls=service.calls if service is not None else None,
                graph=ctx.clientModules.graph(), descriptor=ctx.typert.local.get('pythonWebEcho/echo') is not None,
                seen=ctx.typert.local.hasSeen('pythonWebEcho/echo'), python=sys.version.split()[0])

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
                        value = snapshot()
                    elif command == 'unload':
                        ctx = result['ctx']
                        entry = next(row for row in ctx.loader.entries if row.options.get('name') == NAME)
                        await entry.fiber.dispose()
                        await entry.fiber.await_settled()
                        for _ in range(20):
                            await asyncio.sleep(0)
                        value = snapshot()
                    elif command in ('restart', 'upgrade', 'rollback', 'remove'):
                        await stop()
                        if command == 'upgrade':
                            project = Path(directory) / 'version-two'
                            shutil.copytree(str(ROOT / 'examples/python-web-echo'), str(project))
                            manifest = json.loads((project / 'package.json').read_text(encoding='utf-8'))
                            manifest['version'] = '2.0.0'
                            (project / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
                            source = project / 'python/web_echo/plugin.py'
                            source.write_text(source.read_text(encoding='utf-8').replace("'1.0.0'", "'2.0.0'"), encoding='utf-8')
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
