"""Development-only native Web host for the real-browser Cordis oracle.

Private home/workspace; stdin control only stages source and reads host truth.
Browser lifecycle operations use the unchanged application's real Remote calls.
The model continuation sink is recorded, so this probe makes no paid LLM calls.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dsh.boot.profile_boot import run_profile


async def main():
    with tempfile.TemporaryDirectory(prefix='dsh-native-browser-') as directory:
        home = Path(directory) / 'home'
        workspace = Path(directory) / 'workspace'
        workspace.mkdir()
        os.environ['DSH_HOME'] = str(home)
        os.environ['DSH_TELEMETRY_MODE'] = 'DISABLED'
        result = await run_profile(dict(profile='web', dshHome=str(home),
            args=['--no-open', '--port', '0'], waitForExit=False))
        ctx = result['ctx']
        try:
            sid = 'native-browser-owner'
            await ctx.get('sessionController').create(dict(sessionId=sid,
                cwd=str(workspace), agentPreset='minimal'))
            owner = ctx.get('agents').get(sid)
            steers = []
            owner.steer = lambda message: steers.append(message)
            runner = ctx.get('dynamicCordisRunner')
            events = []
            for name in ('cordis/request-run', 'cordis/request-run-resolved',
                         'cordis/dynamic-package', 'cordis/dynamic-retract'):
                ctx.on(name, lambda value, event=name: events.append(dict(event=event, value=value)))

            def answer(value):
                print('DSH_PROBE ' + json.dumps(value, ensure_ascii=True), flush=True)

            answer(dict(ready=True, url=ctx.get('connection').authenticated_url(
                'http://127.0.0.1:{}'.format(ctx.get('webServer').port)),
                sessionId=sid, workspace=str(workspace), python=sys.version.split()[0],
                clientArtifacts=[dict(name=name, path=meta['client_path'])
                    for name, meta in ctx.get('clientModules')._pkg_meta.items()]))
            while True:
                line = await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                request = json.loads(line)
                try:
                    command = request['command']
                    if command == 'define':
                        value = runner.define(dict(sessionId=sid, plugin=request['plugin'],
                            name=request.get('name', 'Native browser probe'),
                            purpose='Verify original Client over native Python Host', code=request['code']))
                    elif command == 'request-run':
                        value = await runner.run(owner, request['pluginId'], request['packageId'], request.get('mode', 'run'))
                    elif command == 'snapshot':
                        value = dict(inventory=runner.inventory(), events=events,
                            steers=len(steers), pending=list(runner.pending),
                            probe=ctx.get('nativeBrowserProbe'))
                    elif command == 'shutdown':
                        answer(dict(id=request['id'], ok=True, value=None))
                        break
                    else:
                        raise ValueError('unknown probe command')
                    answer(dict(id=request['id'], ok=True, value=value))
                except Exception as error:
                    traceback.print_exc(file=sys.stderr)
                    answer(dict(id=request['id'], ok=False, error=str(error)))
        finally:
            result['shutdown'].shutdown(0)
            await result['shutdown'].wait()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
