"""Real native activation/retirement observations for the pinned source probe."""
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
from dsh.extensions.host_runner import DynamicCordisRunner

HOST = "async def plugin(ctx):\n    ctx.provide('probeValue', 'starting')\n    harness.handle('read', lambda args: args)\n    await ctx.get('runnerGate').wait()\n    ctx.provide('probeLate', 'ready')\n"
PREVIOUS = "def plugin(ctx):\n    ctx.provide('probePrevious', 'ready')\n"


async def observe(spec):
    ctx = Context()
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    runner = ctx.get('dynamicCordisRunner')
    owner, events = NS(id='owner'), []
    for name in ('cordis/request-run', 'cordis/request-run-resolved', 'cordis/dynamic-package', 'cordis/dynamic-retract'):
        ctx.on(name, lambda payload, name=name: events.append([name, copy.deepcopy(payload)]))
    entered, released = asyncio.Event(), asyncio.Event()
    async def wait():
        entered.set()
        await released.wait()
    ctx.provide('runnerGate', NS(wait=wait))
    activation, ending, defined = None, None, None
    def capture():
        return copy.deepcopy(dict(inventory=runner.inventory(),
            values=[ctx.get(name) for name in ('probePrevious', 'probeValue', 'probeLate')],
            starting=len(runner.starting), events=events))
    try:
        if spec['update']:
            defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='probe'), name='Previous', purpose='retirement', code=dict(host=PREVIOUS)))
            await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
        code = dict(host=PREVIOUS if spec.get('settled') else HOST)
        if spec['client']:
            code['client'] = 'return () => {}'
        defined = runner.define(dict(sessionId=owner.id,
            plugin=dict(kind='existing', pluginId=defined['pluginId']) if defined else dict(kind='new', idPrefix='probe'),
            name='Probe', purpose='retirement', code=code))
        mode = 'update' if spec['update'] else 'run'
        if spec['client']:
            await runner.run(owner, defined['pluginId'], defined['packageId'], mode)
            request = next(value for name, value in reversed(events) if name == 'cordis/request-run')
            activation = asyncio.create_task(runner.runHostHalf(owner, defined['pluginId'], defined['packageId'], mode, request['requestId'], False))
        else:
            activation = asyncio.create_task(runner.run(owner, defined['pluginId'], defined['packageId'], mode))
        if spec.get('settled'):
            await activation
        else:
            await asyncio.wait_for(entered.wait(), 1)
        before = capture()
        end_settled = False
        async def end():
            nonlocal end_settled
            result = await getattr(runner, 'undefine' if spec['remove'] else 'stop')(owner, defined['pluginId'])
            end_settled = True
            return result
        ending = asyncio.create_task(end())
        if spec.get('settled'):
            await ending
        # Flush a full event-loop turn, matching the source timer checkpoint.
        await asyncio.sleep(.01)
        during = dict(capture(), endSettled=end_settled)
        released.set()
        started, ended = await asyncio.gather(activation, ending)
        return dict(mode=spec['mode'], before=before, during=during, started=started, ended=ended, after=capture())
    finally:
        released.set()
        await asyncio.gather(*(task for task in (activation, ending) if task is not None), return_exceptions=True)
        await ctx.fiber.dispose()


async def observations():
    specs = json.loads((ROOT / 'scripts/oracles/cordis-retirement-cases.json').read_text(encoding='utf-8'))
    return [await observe(spec) for spec in specs]


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observations()), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
