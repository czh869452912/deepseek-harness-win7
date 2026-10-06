import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
import sys


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--group', choices=('session','errors'), required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0, str(root))
from dsh.cordis.context import Context
from dsh.javascript.runtime import JavaScriptRuntime


async def observe(scenario):
    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    events = []
    ready = False
    result = None
    thrown = None
    worker = None

    def observed(message):
        events.append(dict(message, type='result') if message['type'] == 'terminal' else message)

    try:
        initial = dict(meta=dict(name=scenario['name'], description='engine research'), body=scenario['body'],
            args=dict(nested=dict(value=2)), limits=dict(maxConcurrentAgents=2, maxTotalAgents=10, maxItemsPerCall=30, syncTimeoutMs=200))
        worker = await asyncio.wait_for(ctx.get('jsRuntime').open_workflow(initial, observed, 200), 5)
        ready = worker.ready.done() and not worker.ready.cancelled() and worker.ready.exception() is None
        if ready:
            await worker.send(dict(type='go'))
        result = await asyncio.wait_for(asyncio.shield(worker.result), 5)
    except Exception as caught:
        thrown = dict(name=getattr(caught, 'name', type(caught).__name__), message=getattr(caught, 'message', str(caught)),
            **(dict(code=caught.code) if hasattr(caught, 'code') else {}))
    finally:
        if worker is not None:
            await asyncio.wait_for(worker.dispose(), 5)
        await ctx.fiber.dispose()
    negative = bool(scenario['name'] == 'scalars' and result is not None and math.copysign(1, result['value'][5]) < 0)
    return dict(name=scenario['name'], body=scenario['body'], readyResolved=ready, events=events, result=result,
        negativeZero=negative, **(dict(thrown=thrown) if thrown is not None else {}))


cases = json.loads((Path(__file__).resolve().parent / 'js-error-fixtures.json').read_text(encoding='utf-8'))[arguments.group]
rows = [asyncio.run(observe(scenario)) for scenario in cases]
modules = {}
for name, module in sorted(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if path and (name == 'dsh' or name.startswith('dsh.')):
        selected = Path(path).resolve()
        modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
assets = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for folder in ('dsh/javascript/bin', 'dsh/javascript/workflow') for path in (root / folder).iterdir() if path.is_file()}
with arguments.output.open('x', encoding='utf-8') as stream:
    json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, assets=assets, rows=rows), stream, indent=2)
    stream.write('\n')
