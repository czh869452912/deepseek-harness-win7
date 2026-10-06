import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


async def observe(fixture):
    from dsh.cordis.context import Context
    from dsh.llm.llm_service import LlmRuntime
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    service = ctx.get('llm')
    model = copy.deepcopy(fixture['model'])
    trace, requests, chunks = [], [], []
    class Adapter:
        async def prepare_call(self, provider, identifier, signal=None):
            trace.append(dict(kind='prepare', provider=provider, model=identifier))
            return dict(model=model, stream=self.stream)

        async def stream(self, options):
            trace.append(dict(kind='dispatch'))
            requests.append(options)
            yield dict(type='finish', reason=dict(kind='stop'))

    service.register_adapter(['fixture'], Adapter())
    async def middleware(options, next):
        trace.append(dict(kind='middleware'))
        return await next()
    ctx.on('llm/stream', middleware)
    try:
        async for chunk in service.stream(dict(provider='fixture', model='model', messages=[])):
            chunks.append(chunk)
        return dict(name=fixture['name'], trace=trace, requests=requests, chunks=chunks)
    finally:
        await ctx.fiber.dispose()


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--fixtures', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0, str(root))
fixtures = json.loads(arguments.fixtures.read_text(encoding='utf-8'))['fixtures']
rows = [asyncio.run(observe(fixture)) for fixture in fixtures]
modules = {}
for name, module in sorted(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if path and (name == 'dsh' or name.startswith('dsh.')):
        selected = Path(path).resolve()
        modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
with arguments.output.open('x', encoding='utf-8') as stream:
    json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, indent=2)
    stream.write('\n')
