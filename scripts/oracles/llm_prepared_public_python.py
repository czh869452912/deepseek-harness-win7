import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


async def observe(name):
    from dsh.cordis.context import Context
    from dsh.core.session.json import FrozenDict, FrozenList
    from dsh.llm.llm_service import LlmRuntime
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    service = ctx.get('llm')
    trace, requests, chunks, errors = [], [], [], []
    model = dict(provider='fixture', id='model', name='Model', inputModalities=['text'], context=dict(contextWindow=100),
        defaultMaxTokens=256, reasoning=dict(efforts=[dict(id='low', name='Low'), dict(id='high', name='High')], defaultEffort='low'))
    class Adapter:
        def __init__(self, generation):
            self.generation = generation

        async def prepare_call(self, provider, identifier, signal=None):
            trace.append(dict(kind='prepare', generation=self.generation, provider=provider, model=identifier))
            captured = self.generation
            return dict(model=model, stream=lambda options: self.dispatch(options, captured))

        async def dispatch(self, options, generation):
            trace.append(dict(kind='dispatch', generation=generation))
            requests.append(options)
            yield dict(type='finish', reason=dict(kind='stop'))

    dispose = service.register_adapter(['fixture'], Adapter('first'))
    async def middleware(options, next):
        trace.append(dict(kind='middleware'))
        if name == 'middleware-config':
            options['model'] = 'foreign'
        return await next()
    ctx.on('llm/stream', middleware)
    config = dict(provider='fixture', model='model', temperature=0.5, stop=['END'])
    if name != 'defaults':
        config.update(maxTokens=128, reasoningEffort='high')
    try:
        prepared = await service.prepareCall(config)
        observed = {field: copy.deepcopy(prepared[field]) for field in ('config', 'adapterDefaults', 'context', 'inputModalities', 'retryPolicy') if field in prepared}
        observed['frozen'] = dict(handle=isinstance(prepared, FrozenDict), config=isinstance(prepared.get('config'), FrozenDict),
            stop=isinstance(prepared.get('config', {}).get('stop'), FrozenList), defaults=isinstance(prepared.get('adapterDefaults'), FrozenDict),
            context=isinstance(prepared.get('context'), FrozenDict), modalities=isinstance(prepared.get('inputModalities'), FrozenList))
        options = dict(prepared.get('config', config), messages=[])
        for field in ('maxTokens', 'reasoningEffort'):
            if field in prepared and prepared[field] is not None:
                options[field] = prepared[field]
        if name == 'replace-registration':
            dispose()
            service.register_adapter(['fixture'], Adapter('second'))
        if name == 'mutate-input':
            config['model'] = 'foreign'
            config['stop'].append('LATE')
        if name == 'mutate-model':
            model['inputModalities'].append('image')
            model['context']['contextWindow'] = 200
            model['reasoning']['efforts'][0]['name'] = 'Changed'
        if name.startswith('mismatch-') and name != 'mismatch-then-valid':
            field = name[len('mismatch-'):]
            options[field] = ['OTHER'] if field == 'stop' else 0.7 if field == 'temperature' else 129 if field == 'maxTokens' else 'foreign'
        async def drain(selected, late=False):
            try:
                stream = prepared['stream'](selected)
                if late:
                    selected['model'] = 'foreign'
                async for chunk in stream:
                    chunks.append(chunk)
            except Exception as caught:
                errors.append(dict(name=getattr(caught, 'name', type(caught).__name__), message=getattr(caught, 'message', str(caught)), **(dict(code=caught.code) if hasattr(caught, 'code') else {})))
        if name == 'mismatch-then-valid':
            await drain(dict(options, model='foreign'))
        await drain(options, name == 'late-config')
        if name == 'repeat':
            await drain(options)
        return dict(name=name, observed=observed, trace=trace, requests=requests, chunks=chunks, errors=errors,
            after={field: prepared[field] for field in ('config', 'context', 'inputModalities') if field in prepared})
    finally:
        await ctx.fiber.dispose()


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0, str(root))
names = ('plain', 'defaults', 'repeat', 'mismatch-provider', 'mismatch-model', 'mismatch-temperature', 'mismatch-maxTokens',
    'mismatch-reasoningEffort', 'mismatch-stop', 'mismatch-then-valid', 'late-config', 'middleware-config', 'replace-registration', 'mutate-input', 'mutate-model')
rows = [asyncio.run(observe(name)) for name in names]
modules = {}
for name, module in sorted(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if path and (name == 'dsh' or name.startswith('dsh.')):
        selected = Path(path).resolve()
        modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
with arguments.output.open('x', encoding='utf-8') as stream:
    json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, indent=2)
    stream.write('\n')
