import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys


async def observe(name):
    from dsh.cordis.context import Context
    from dsh.llm.llm_service import LlmRuntime
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    requests, chunks, errors = [], [], []

    class Adapter:
        async def prepare_call(self, provider, model, signal=None):
            return dict(model=dict(provider=provider, id=model, name=model), stream=self.stream)

        async def stream(self, options):
            requests.append(options)
            yield dict(type='finish', reason=dict(kind='stop'))

    ctx.get('llm').register_adapter(['fixture'], Adapter())
    config = dict(provider='fixture', model='model')
    if name in ('tokens-number-bool', 'same-numbers'):
        config['maxTokens'] = 1
    if name == 'tokens-bool-number':
        config['maxTokens'] = True
    if name in ('temperature-number-bool', 'same-numbers'):
        config['temperature'] = 1
    if name == 'temperature-bool-number':
        config['temperature'] = True
    if name == 'stop-number-bool':
        config['stop'] = [1]
    if name == 'stop-bool-number':
        config['stop'] = [True]
    if name == 'tokens-null-absent':
        config['maxTokens'] = None
    if name == 'temperature-null-absent':
        config['temperature'] = None
    if name == 'same-stop-copy':
        config['stop'] = ['END', '']
    try:
        prepared = await ctx.get('llm').prepareCall(config)
        options = dict(prepared.get('config', config), messages=[])
        if name == 'tokens-number-bool':
            options['maxTokens'] = True
        if name == 'tokens-bool-number':
            options['maxTokens'] = 1
        if name == 'temperature-number-bool':
            options['temperature'] = True
        if name == 'temperature-bool-number':
            options['temperature'] = 1
        if name == 'stop-number-bool':
            options['stop'] = [True]
        if name == 'stop-bool-number':
            options['stop'] = [1]
        if name == 'tokens-absent-null':
            options['maxTokens'] = None
        if name == 'tokens-null-absent':
            options.pop('maxTokens', None)
        if name == 'temperature-absent-null':
            options['temperature'] = None
        if name == 'temperature-null-absent':
            options.pop('temperature', None)
        if name == 'reasoning-absent-null':
            options['reasoningEffort'] = None
        if name == 'same-stop-copy':
            options['stop'] = list(options['stop'])
        if name == 'ignored-extra':
            options['extra'] = 'retained'
        try:
            async for chunk in prepared['stream'](options):
                chunks.append(chunk)
        except Exception as caught:
            errors.append(dict(name=getattr(caught, 'name', type(caught).__name__), message=getattr(caught, 'message', str(caught)),
                **(dict(code=caught.code) if hasattr(caught, 'code') else {})))
        return dict(name=name, **{field:prepared[field] for field in ('config','adapterDefaults') if field in prepared}, options=options,
            requests=requests, chunks=chunks, errors=errors)
    finally:
        await ctx.fiber.dispose()


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0, str(root))
names = ('tokens-number-bool', 'tokens-bool-number', 'temperature-number-bool', 'temperature-bool-number',
    'stop-number-bool', 'stop-bool-number', 'tokens-absent-null', 'tokens-null-absent', 'temperature-absent-null',
    'temperature-null-absent', 'reasoning-absent-null', 'same-numbers', 'same-stop-copy', 'ignored-extra')
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
