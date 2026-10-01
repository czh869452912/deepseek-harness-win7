"""Actual Python Host lifecycle for the shared pinned runner journeys.

Only fixture Host source is translated explicitly. Client source is unchanged;
this does not interpret arbitrary JavaScript or simulate browser activation.
"""
import asyncio
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin
from dsh.core.abort import AbortController
from dsh.extensions.host_runner import DynamicCordisRunner

CLIENT = 'return () => {}'
HOST = "def plugin(ctx):\n    ctx.provide('probeValue', 'ready')\n    harness.handle('read', lambda args: args)\n"
WAITING = "def plugin(ctx):\n    harness.handle('read', lambda args: args)\nplugin.inject = ['runnerDependency']\n"
REPLACE = "def plugin(ctx):\n    old = harness.handle('read', lambda args: 'old')\n    harness.handle('read', lambda args: args)\n    old()\n"
FAIL = "def plugin(ctx):\n    raise ValueError('fixture apply failure')\n"
GATE = "async def plugin(ctx):\n    await ctx.get('runnerGate').wait()\n    ctx.provide('probeValue', 'ready')\n"
ERRORS = "def plugin(ctx):\n    def fail(message):\n        error = ValueError(message)\n        error.stack = 'fixture stack'\n        raise error\n    harness.handle('a\\x00b', lambda args: fail('c'))\n    harness.handle('a', lambda args: fail('b\\x00c'))\n"


async def observe(spec):
    ctx = Context()
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    runner = ctx.get('dynamicCordisRunner')
    events, steered, injected = [], [], []
    for name in ('cordis/request-run', 'cordis/request-run-resolved', 'cordis/dynamic-package', 'cordis/dynamic-retract'):
        ctx.on(name, lambda payload, name=name: events.append([name, copy.deepcopy(payload)]))
    def message(value):
        assert isinstance(value['id'], str)
        return {key: item for key, item in value.items() if key != 'id'}
    owner = NS(id='owner', steer=lambda value: steered.append(message(value)), inject=lambda value: injected.append(message(value)))
    foreign = NS(id='foreign', steer=lambda _: None, inject=lambda _: None)
    impostor = NS(**vars(owner))
    ctx.provide('agents', dict(owner=owner, foreign=foreign))
    entered, released, pending = asyncio.Event(), asyncio.Event(), None
    async def gate_wait():
        entered.set()
        await released.wait()
    ctx.provide('runnerGate', NS(wait=gate_wait))
    saved, rows, defined, last_half, request = {}, [], None, None, None
    def refs(value):
        if isinstance(value, str) and value.startswith('$'):
            result = saved
            for key in value[1:].split('.'):
                result = result[key]
            return result
        if isinstance(value, list):
            return [refs(item) for item in value]
        if isinstance(value, dict):
            return {key: refs(item) for key, item in value.items()}
        return value
    try:
        for raw in spec['steps']:
            step = refs(raw)
            agent = foreign if step.get('agent') == 'foreign' else impostor if step.get('agent') == 'impostor' else owner
            before = [len(events), len(steered), len(injected)]
            pid, package = (defined['pluginId'], defined['packageId']) if defined else (None, None)
            op = step['op']
            try:
                if op == 'define':
                    code = {}
                    program = step['program']
                    if program != 'client':
                        code['host'] = dict(waiting=WAITING, errors=ERRORS, replace=REPLACE, fail=FAIL, gate=GATE).get(program, HOST)
                    if program in ('dual', 'client', 'waiting'):
                        code['client'] = CLIENT
                    defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='existing', pluginId=pid) if step['existing'] else dict(kind='new', idPrefix='probe'), name='Probe', purpose='actual lifecycle', code=code))
                    value = defined
                elif op == 'reference':
                    value = runner.reference(agent, pid)
                elif op == 'run':
                    controller = AbortController()
                    if step.get('aborted'):
                        controller.abort('fixture abort')
                    value = await runner.run(agent, pid, package, step['mode'], controller.signal)
                elif op == 'begin':
                    pending = asyncio.create_task(runner.run(agent, pid, package, 'run'))
                    await asyncio.wait_for(entered.wait(), 1)
                    value = None
                elif op == 'release':
                    released.set()
                    value = None
                elif op == 'join':
                    value = await pending
                elif op == 'request':
                    request = next(payload for name, payload in reversed(events) if name == 'cordis/request-run')
                    value = request
                elif op == 'half':
                    last_half = await runner.runHostHalf(agent, pid, package, step.get('mode', 'run' if step['direct'] else request['mode']), None if step['direct'] else request['requestId'], step.get('future', False))
                    value = last_half
                elif op == 'clientCode':
                    value = runner.getClientCode(agent, pid, step.get('runId', last_half['pluginRunId']))
                elif op == 'resolve':
                    value = await runner.resolveRequestRun(request['requestId'], step['resolution'])
                elif op == 'resolveRace':
                    value = await asyncio.gather(runner.resolveRequestRun(request['requestId'], step['resolution']), runner.resolveRequestRun(request['requestId'], step['resolution']))
                elif op == 'settle':
                    value = await runner.settleUserRun(agent, pid, step['resolution'])
                elif op in ('stop', 'undefine', 'panelStop', 'panelDelete'):
                    value = await getattr(runner, dict(panelStop='stopFromPanel', panelDelete='undefineFromPanel').get(op, op))(agent, pid)
                elif op == 'provide':
                    ctx.provide('runnerDependency', {})
                    await asyncio.sleep(.01)
                    value = None
                elif op == 'invoke':
                    active = runner.inventory()[0].get('activeRun', {}) if runner.inventory() else {}
                    value = await runner.invoke(pid, active.get('pluginRunId', 'stale'), step['method'], step['args'])
                elif op in ('guard', 'render'):
                    method = runner.reportClientGuardFailure if op == 'guard' else runner.reportRenderFailure
                    value = await method(agent, pid, step.get('runId', last_half['pluginRunId']), step['failure'])
                else:
                    raise ValueError('unknown operation ' + op)
                if 'save' in step:
                    saved[step['save']] = value
            except Exception as error:
                value = dict(error=dict(message=str(error)))
            grants = [dict(pluginId=plugin['pluginId'], approved=sorted(plugin['approved']), future=plugin['approveFuture']) for plugin in runner.plugins.values()]
            rows.append(copy.deepcopy(dict(op=op, value=value, inventory=runner.inventory(), grants=grants,
                events=events[before[0]:], steer=steered[before[1]:], inject=injected[before[2]:], provided=ctx.get('probeValue'))))
        return dict(mode=spec['mode'], rows=rows)
    finally:
        released.set()
        if pending is not None:
            await pending
        await ctx.fiber.dispose()


async def observations():
    specs = json.loads((ROOT / 'scripts/oracles/cordis-runner-cases.json').read_text(encoding='utf-8'))
    return [await observe(spec) for spec in specs]


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observations()), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
