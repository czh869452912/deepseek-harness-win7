"""Exercise staged rc.3 bindings against an actual, separately built Source."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import traceback
from unittest.mock import patch
from contextlib import ExitStack
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dsh.boot.plugin_registry import HARNESS_PLUGIN_CLASSES
from dsh.boot.plugin_registry_current import CURRENT_HARNESS_PLUGIN_CLASSES
from dsh.boot.profile import _workspace_manifests
from dsh.boot.profile_boot import run_profile
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.cordis.fiber import FiberState
from dsh.typert.current import CurrentRemoteDispatcher
from scripts.oracles.agent_machine_current_python import ScriptAdapter
from dsh.context.session_reference import mention

TARGET = 'a4c74a91e06b00fe0b0937bde982170c526cc842'


def frozen_inputs(source, production=False):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source)] + list(args), encoding='utf-8').strip()
    assert git('rev-parse', 'HEAD') == TARGET and not git('status', '--porcelain'), 'Unchanged rc.3 Source required'
    paths = [Path(__file__).resolve(), ROOT / 'dsh/boot/plugin_registry_current.py', ROOT / 'dsh/client/surfaces_current.py']
    paths += [ROOT / (binding.split(':')[0].replace('.', '/') + '.py') for binding in CURRENT_HARNESS_PLUGIN_CLASSES.values()]
    paths += [Path(path) for path in _workspace_manifests(str(source))]
    paths += [source / '.dsh-build/client-build-environment.json', source / 'apps/web/dist/index.html']
    paths += list(source.glob('packages/*/*/lib/typert.host.js'))
    if production:
        paths += [ROOT / 'dsh/boot/plugin_registry.py', ROOT / 'dsh/boot/profile_boot.py', ROOT / 'dsh/boot/app_boot.py',
                  ROOT / 'scripts/runtime-inputs.json', ROOT / 'scripts/frontend-inputs.json']
        runtime = json.loads((ROOT / 'scripts/runtime-inputs.json').read_text(encoding='utf-8'))
        frontend = json.loads((ROOT / 'scripts/frontend-inputs.json').read_text(encoding='utf-8'))
        paths += [ROOT / row['path'] for row in runtime['files'] + runtime.get('native_files', []) + frontend['files'] + frontend['client_files']]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(paths))}


async def probe(source, output, production=False):
    index = {json.loads(Path(path).read_text(encoding='utf-8'))['name']: str(Path(path).parent)
             for path in _workspace_manifests(str(source))}
    assert index, 'Source workspace packages missing'
    environment = dict(os.environ, DSH_HOME=str(output / 'home'), DSH_TELEMETRY_MODE='DISABLED')
    overlay = output / 'probe.patch.yml'
    overlay.write_text(yaml.safe_dump([dict(id='agent-presets', config=dict(default='standard',
        roots=[dict(path=str(source / 'packages/preset/agent-presets/presets'), trust='system')],
        includeShippedRoot=False, includeUserRoot=False))]), encoding='utf-8')
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        if not production:
            stack.enter_context(patch.dict(HARNESS_PLUGIN_CLASSES, CURRENT_HARNESS_PLUGIN_CLASSES))
            stack.enter_context(patch('dsh.boot.profile.workspace_package_index', return_value=index))
            stack.enter_context(patch('dsh.bundle.web_app.runtime.SOURCE_ROOT', source))
            stack.enter_context(patch('dsh.boot.profile_boot.INSTALL_ANCHOR', str(source / 'apps/cli/package.json')))
        snapshot = LaunchEnvironmentSnapshot([dict(source='process', values=environment)])
        result = await run_profile(dict(profile='web', dshHome=environment['DSH_HOME'], environment=snapshot,
                                        patchFiles=[] if production else [str(overlay)],
                                        args=['--no-open', '--port', '0'], waitForExit=False))
        ctx = result['ctx']
        try:
            rows = []
            for entry in ctx.get('loader').entries():
                rows.append(dict(id=entry.options.get('id'), name=entry.options.get('name'), disabled=entry.disabled,
                                 state=entry.fiber.state if entry.fiber else None))
            (output / 'activation.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
            assert ctx.get('sessionController') is not None
            assert ctx.get('workspaceFiles') is not None
            assert ctx.get('fileUploads') is not None
            assert ctx.get('webServer')._is_running
            assert all(row['disabled'] or row['state'] == FiberState.ACTIVE for row in rows), rows
            graph = ctx.get('clientModules').graph()
            (output / 'client-graph.json').write_text(json.dumps(graph, indent=2), encoding='utf-8')
            print('Client rows:', len(graph['entries']), flush=True)
            remote = CurrentRemoteDispatcher(ctx)
            async def call(method, request):
                assert ctx.get('typert').local.get('session/' + method) is not None, 'Strict descriptor missing'
                return await remote.invoke(dict(namespace='session', method=method, args=dict(request=request)))
            class ProbeAdapter(ScriptAdapter):
                async def resolve_model(self, provider, model, signal=None):
                    info = await super().resolve_model(provider, model, signal)
                    return dict(info, context=dict(contextWindow=131072))
            ctx.get('llm').registerAdapter(['composition-probe'], ProbeAdapter(dict(script=[[
                dict(type='text-delta', index=0, text='complete probe answer'),
                dict(type='finish', reason=dict(kind='stop'))] for _ in range(12)])))
            journeys = []
            for preset in (('minimal', 'standard', 'ptc', 'cordis') if production else ('minimal', 'standard', 'ptc')):
                sid = 'probe-' + preset
                print('Preset:', preset, flush=True)
                created = await call('create', dict(sessionId=sid, cwd=str(output), agentPreset=preset))
                await call('selectModel', dict(sessionId=sid, provider='composition-probe', model='probe-model'))
                await call('prompt', dict(sessionId=sid, requestId='prompt-' + preset, mode='queue',
                                         content=[dict(type='text', text='complete the composition probe')]))
                agent = ctx.get('agents').get(sid)
                if production and preset == 'minimal':
                    assert sorted(row['name'] for row in ctx.get('tools').schemas(agent)) == ['pwsh', 'str_replace_editor']
                if production and preset == 'cordis':
                    assert 'cordis_define' in [row['name'] for row in ctx.get('tools').schemas(agent)]
                await asyncio.wait_for(agent.whenIdle(), 10)
                events = agent.session.snapshotEvents()
                assert any(event['type'] == 'assistant/message' for event in events), events
                assert events[-1]['type'] == 'turn/end' and events[-1]['data']['reason']['kind'] == 'completed', events
                await ctx.get('sessions').flush(agent.session)
                journeys.append(dict(preset=preset, created=created, events=events))
                (output / 'journeys.json').write_text(json.dumps(journeys, indent=2), encoding='utf-8')
            await call('prompt', dict(sessionId='probe-standard', requestId='reference', mode='queue',
                                     content=[dict(type='text', text='Use ' + mention('probe-minimal', 'Minimal'))]))
            agent = ctx.get('agents').get('probe-standard')
            await asyncio.wait_for(agent.whenIdle(), 10)
            assert any(event['type'] == 'user/message' and event['data']['source']['kind'] == 'session-reference'
                       for event in agent.session.events), agent.session.events
            assert agent.session.events[-1]['data']['reason']['kind'] == 'completed'
            await ctx.get('sessions').flush(agent.session)
            (output / 'reference-journey.json').write_text(json.dumps(agent.session.snapshotEvents(), indent=2), encoding='utf-8')
            return rows
        finally:
            result['shutdown'].shutdown(0)
            await result['shutdown'].wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--production', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, code = time.monotonic(), 1
    try:
        before = frozen_inputs(args.source.resolve(), args.production)
        (args.output / 'inputs.json').write_text(json.dumps(dict(target=TARGET, files=before), indent=2), encoding='utf-8')
        rows = asyncio.run(probe(args.source.resolve(), args.output.resolve(), args.production))
        assert frozen_inputs(args.source.resolve(), args.production) == before, 'Candidate inputs changed during probe'
        code = 0
        print(json.dumps(dict(entries=len(rows), active=sum(row['state'] == FiberState.ACTIVE for row in rows))))
    except BaseException:
        (args.output / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
    finally:
        (args.output / 'command.json').write_text(json.dumps(dict(command=sys.argv, exit=code,
            elapsed=time.monotonic() - started)), encoding='utf-8')


if __name__ == '__main__':
    main()
