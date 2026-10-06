import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


async def observe(fixture, operation, detach=False):
    from dsh.cordis.context import Context
    from dsh.llm.llm_service import LlmRuntime
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    service = ctx.get('llm')
    model = copy.deepcopy(fixture['model'])
    trace = []
    class Adapter:
        async def list_models(self, provider):
            trace.append(dict(kind='catalog', provider=provider))
            return [model]

        async def resolve_model(self, provider, identifier, signal=None):
            trace.append(dict(kind='resolve', provider=provider, model=identifier))
            return model

    service.register_adapter(['fixture'], Adapter())
    try:
        try:
            result = await service.list_models('fixture') if operation == 'catalog' else await service.resolve_model_info('fixture', 'model')
            if detach:
                before = copy.deepcopy(result)
                model['name'] = 'Changed'
                model['inputModalities'].append('image')
                model['context']['contextWindow'] = 200
                model['reasoning']['efforts'][0]['name'] = 'Changed'
                return dict(name='detach-' + operation, trace=trace, before=before, after=result, source=model)
            return dict(name=fixture['name'] + '-' + operation, trace=trace, result=result)
        except Exception as error:
            return dict(name=fixture['name'] + '-' + operation, trace=trace, error=dict(name=getattr(error, 'name', type(error).__name__), message=getattr(error, 'message', str(error)), **(dict(code=error.code) if hasattr(error, 'code') else {})))
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
rows = [asyncio.run(observe(fixture, operation)) for fixture in fixtures for operation in ('catalog', 'resolve')]
detach_fixture = dict(model=dict(provider='fixture', id='model', name='Model', inputModalities=['text'], context=dict(contextWindow=100), reasoning=dict(efforts=[dict(id='low', name='Low')], defaultEffort='low')))
rows.extend(asyncio.run(observe(detach_fixture, operation, True)) for operation in ('catalog', 'resolve'))
modules = {}
for name, module in sorted(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if path and (name == 'dsh' or name.startswith('dsh.')):
        selected = Path(path).resolve()
        modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
with arguments.output.open('x', encoding='utf-8') as stream:
    json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, indent=2)
    stream.write('\n')
