import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsh.cordis import Context
from dsh.subagent.acp import AcpProvider, CONFIG, SubagentAcp
from dsh.subprocess.local import LocalSubprocessRuntime


ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def request(cwd, controller):
    return {'parent': SimpleNamespace(session=SimpleNamespace(header={'cwd': str(cwd)})),
        'signal': controller.signal, 'prompt': [{'type': 'image', 'source': {'type': 'url', 'url': 'private-parent'}},
        {'type': 'text', 'text': 'explicit child task'}]}


async def wait_file(path):
    deadline = asyncio.get_running_loop().time() + 10
    while not path.exists():
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError('ACP peer readiness not observed')
        await asyncio.sleep(0.01)


async def native_observations(workspace, row):
    scenario = row['scenario']
    record = workspace / ('native-' + row['name'] + '.jsonl')
    env = dict(scenario['env'], PROBE_RECORD=str(record))
    if row['name'] == 'flush':
        env['PROBE_FLUSH'] = str(workspace / 'native-flush')
    if scenario.get('cancel'):
        env['PROBE_READY'] = str(workspace / 'native-ready')
    ctx, observations, errors = Context(), {}, []
    await ctx.plugin(LocalSubprocessRuntime)
    service = ctx.get('subprocess')
    child = None
    spawn = service.spawn
    def capture(spec):
        nonlocal child
        child = spawn(spec)
        return child
    service.spawn = capture
    config = CONFIG({'command': scenario.get('command', sys.executable),
        'args': [str(ROOT / 'scripts/oracles/subagent_acp_peer.py')], 'env': env,
        'permission': scenario.get('policy', 'reject'), 'disposeEofGraceMs': 150, 'disposeGraceMs': 100})
    backend = AcpProvider(ctx, config)
    backend.report = lambda error, reason: errors.append(error)
    run = None
    from dsh.core.abort import AbortController
    controller = AbortController()
    try:
        try:
            run = await backend.start(request(workspace, controller))
            if scenario.get('cancel'):
                await wait_file(Path(env['PROBE_READY']))
                controller.abort('local cancel')
            observations['result'] = await run.result
            if scenario.get('cancel'):
                deadline = asyncio.get_running_loop().time() + 10
                while not record.exists() or '"method": "session/cancel"' not in record.read_text(encoding='utf-8'):
                    assert asyncio.get_running_loop().time() < deadline, 'ACP cancel delivery not observed'
                    await asyncio.sleep(0.01)
            observations['idDistinct'] = run.id != 'same-child-id'
            observations['localAgentAbsent'] = run.localAgent is None
            await run.dispose()
            await run.dispose()
        except Exception as error:
            observations['error'] = {'name': getattr(error, 'name', 'Error'), 'message': str(error)}
        observations['quiescent'] = await child.wait_for_exit()
        observations['exitCode'] = None if child.pid <= 0 else (await child.done).exitCode
        observations['errorCount'] = len(errors)
        observations['records'] = [json.loads(line) for line in record.read_text(encoding='utf-8').splitlines()] if record.exists() else []
        observations['spawned'] = child.pid > 0
        observations['flushed'] = Path(env['PROBE_FLUSH']).exists() if row['name'] == 'flush' else False
        return observations
    finally:
        if run is not None:
            await run.dispose()
        await ctx.fiber.dispose()


def public_observation(raw):
    result = dict(raw)
    packets = raw['records']
    result['wire'] = [{key: packet[key] for key in ('method', 'params', 'result') if key in packet}
                      for packet in packets if 'method' in packet or 'result' in packet]
    result['processFacts'] = {'spawns': sum('spawn' in packet for packet in packets),
                             'closes': sum(packet.get('closed') is True for packet in packets)}
    del result['records']
    return result


def native_configurations(rows):
    observations = []
    for row in rows:
        captured = []
        registry = SimpleNamespace(registerProvider=captured.append)
        context = SimpleNamespace(get=lambda name: registry)
        observation = {'input': row['input']}
        try:
            config = CONFIG(row['input'])
            SubagentAcp(context, config).apply(context)
            backend = captured[0]
            observation['result'] = {'config': config, 'name': backend.name,
                'capabilities': backend.capabilities, 'inheritsParentContext': backend.inheritsParentContext}
        except Exception as error:
            observation['error'] = {'name': getattr(error, 'name', 'Error'), 'message': str(error)}
        observations.append(observation)
    return observations


async def native_runner(workspace, source):
    rows = []
    for row in source['rows']:
        rows.append({'name': row['name'], 'scenario': row['scenario'],
                     'observations': await native_observations(workspace, row)})
    return {'rows': rows, 'configurations': native_configurations(source['configurations'])}


if __name__ == '__main__':
    workspace, source_file, output_file = map(Path, sys.argv[1:])
    source = json.loads(source_file.read_text(encoding='utf-8'))
    result = asyncio.run(native_runner(workspace, source))
    output_file.write_text(json.dumps(result, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
