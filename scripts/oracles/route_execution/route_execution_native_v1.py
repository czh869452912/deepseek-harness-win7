import argparse
import asyncio
import builtins
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--run-dir', type=Path, required=True)
parser.add_argument('--workspace', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--port', default='0')
options = parser.parse_args()
root = options.root.resolve()
sys.path.insert(0, str(root))
import yaml
from dsh.boot.profile_boot import run_profile
from dsh.llm.message import create_user_message


async def main():
    output = options.output.resolve()
    assert not output.exists()
    run = options.run_dir.resolve()
    assert not run.exists()
    profile = run / 'home/profiles/web'
    profile.mkdir(parents=True)
    workspace = options.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    fixture = Path(__file__).resolve().with_name('route_execution_fixture_v1.py')
    (profile / 'package.json').write_text(json.dumps(dict(name='route-execution-fixture', private=True,
        type='module', dsh=dict(profile=dict(bundles=['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'],
            patchReload='startup')))) + '\n', encoding='utf-8')
    patch = [dict(insert=[dict(id='route-execution-fixture', name=str(fixture) + ':FixturePlugin')]),
        dict(id='agent-default-model', config=dict(provider='route-alpha', model='parent')),
        dict(id='subagent-model-selection-settings', config=dict(enabled=True,
            allowedModels=[dict(provider='route-alpha', model='parent'), dict(provider='route-beta', model='child')])),
        dict(id='session-persistence-jsonl', config=dict(root=str(run / 'sessions'), packChunks=False)),
        dict(id='session-title-llm', disabled=True)]
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump(patch), encoding='utf-8')
    os.environ['DSH_HOME'] = str(run / 'home')
    os.environ['DSH_TELEMETRY_DISABLED'] = '1'
    os.chdir(str(workspace))
    time.time = lambda: 1791244800
    record = dict(root=str(root), python=sys.version, executable=sys.executable, observedClock=1791244800000,
        lookups=[], requests=[], events=[], created=[], disposed=[], cancellation=[], rows=[],
        fixtureSha256=hashlib.sha256(fixture.read_bytes()).hexdigest())
    builtins.__route_execution_probe = record
    runtime = None
    try:
        runtime = await run_profile(dict(profile='web', args=['--no-open', '--port', options.port], waitForExit=False))
        ctx = runtime['ctx']
        record['port'] = ctx.get('webServer').port
        for scenario in ('SPAWN_INHERIT', 'SPAWN_CHANGE', 'SPAWN_EFFORT', 'DENIED_ROUTE', 'HALF_ROUTE', 'FORK_INHERIT', 'CANCEL'):
            offsets = {key: len(record[key]) for key in ('lookups', 'requests', 'events', 'created', 'disposed', 'cancellation')}
            record['childStarted'] = asyncio.Event()
            identity = 'route-parent-' + scenario.lower()
            await ctx.get('sessionController').create(dict(sessionId=identity, cwd=str(workspace), agentPreset='standard'))
            parent = ctx.get('agents').get(identity)
            parent.followup(create_user_message(dict(content=[dict(type='text', text=scenario)], source=dict(kind='user'))))
            if scenario == 'CANCEL':
                await asyncio.wait_for(record['childStarted'].wait(), 30)
                parent.cancel(dict(kind='user'))
            await asyncio.wait_for(parent.when_idle(), 30)
            await ctx.get('sessions').flush(parent.session)
            record['rows'].append(dict(name=scenario, parentHeader=parent.session.header.to_dict(),
                parentStatus=parent.status, public={key: copy.deepcopy(record[key][offset:]) for key, offset in offsets.items()}))
    except Exception as error:
        record['failure'] = dict(name=type(error).__name__, message=str(error))
        raise
    finally:
        record.pop('childStarted', None)
        if runtime is not None:
            runtime['shutdown'].shutdown(1 if record.get('failure') else 0)
            await runtime['shutdown'].wait()
            record['exitCode'] = runtime['shutdown'].exit_code
        record['modules'] = {}
        for module in tuple(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename:
                path = Path(filename).resolve()
                if path.is_file() and root in path.parents and path.relative_to(root).parts[0] in ('dsh', 'apps', 'packages'):
                    record['modules'][path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
asyncio.run(main())
