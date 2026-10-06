import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


async def observe(name):
    from dsh.cordis.context import Context
    from dsh.core.abort import AbortController
    from dsh.core.session.json import FrozenDict, FrozenList, deep_freeze
    from dsh.llm.llm_service import LlmRuntime
    from dsh.llm.retry_policy import resolve_retry_policy
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    service = ctx.get('llm')
    trace, requests, chunks, errors = [], [], [], []
    controller = AbortController()
    pending, ready = asyncio.Event(), asyncio.Event()
    config = dict(provider='fixture', model='model', stop=['END'])
    model = dict(provider='fixture', id='model', name='Model', inputModalities=['text'], context=dict(contextWindow=100), defaultMaxTokens=256)

    class BaseAdapter:
        def __init__(self, generation):
            self.generation = generation

        def provider_retry_policy(self, provider):
            return resolve_retry_policy(dict(mode='normal', maxRetries=2 if self.generation == 'first' else 7))

        async def resolve_model(self, provider, identifier, signal=None):
            trace.append(dict(kind='resolve', generation=self.generation, provider=provider, model=identifier, signalSame=signal is controller.signal))
            return model

        async def stream(self, options):
            trace.append(dict(kind='dispatch', generation=self.generation))
            requests.append(dict(values={field: value for field, value in options.items() if field != 'signal'},
                signalSame=options.get('signal') is controller.signal, frozen=isinstance(options, FrozenDict),
                messagesFrozen=isinstance(options.get('messages'), FrozenList)))
            yield dict(type='finish', reason=dict(kind='stop'))

    class Adapter(BaseAdapter):
        async def prepare_call(self, provider, identifier, signal=None):
            trace.append(dict(kind='prepare', generation=self.generation, provider=provider, model=identifier, signalSame=signal is controller.signal))
            if name.startswith('pending-'):
                ready.set()
                await pending.wait()
            return dict(model=model, stream=self.stream)

    first = BaseAdapter('first') if name == 'default-adapter' else Adapter('first')
    dispose = lambda: None
    if name != 'missing-provider':
        dispose = service.register_adapter(['fixture', 'history'] if name == 'shared-replay' else ['fixture'], first)
    if name == 'foreign-replay':
        service.register_adapter(['history'], Adapter('second'))

    async def middleware(options, next):
        trace.append(dict(kind='middleware'))
        return await next()

    ctx.on('llm/stream', middleware)
    observed = None
    try:
        preparing = asyncio.create_task(service.prepareCall(config, controller.signal))
        if name.startswith('pending-'):
            await ready.wait()
            if name == 'pending-config':
                config['model'] = 'foreign'
            else:
                dispose()
                if name == 'pending-register':
                    service.register_adapter(['fixture'], Adapter('second'))
            pending.set()
        prepared = await preparing
        observed = {field: copy.deepcopy(prepared[field]) for field in ('config', 'retryPolicy', 'adapterDefaults', 'context', 'inputModalities') if field in prepared}
        if name in ('held-replay', 'new-current-owner'):
            dispose()
            service.register_adapter(['fixture'], first if name == 'held-replay' else Adapter('second'))
        history = 'replay' in name or name == 'new-current-owner'
        messages = [dict(id='fixed-message', role='assistant', content=[dict(type='text', text='earlier')],
            source=dict(kind='model', provider='history' if name in ('shared-replay', 'foreign-replay') else 'fixture',
                model='old-model', replayState=dict(opaque='state')))] if history else []
        options = dict(prepared.get('config', config), messages=messages, signal=controller.signal)
        if history:
            options = deep_freeze(options)
        selected = prepared['stream'](options)
        if name == 'unconsumed-repeat':
            try:
                prepared['stream'](options)
            except Exception as caught:
                errors.append(error_record(caught))
        async for chunk in selected:
            chunks.append(chunk)
    except Exception as caught:
        errors.append(error_record(caught))
    finally:
        pending.set()
        await ctx.fiber.dispose()
    return dict(name=name, **(dict(observed=observed) if observed is not None else {}), trace=trace, requests=requests,
        chunks=chunks, errors=errors, signal=dict(frozen=isinstance(controller.signal, (FrozenDict, FrozenList)), aborted=controller.signal.aborted))


def error_record(caught):
    return dict(name=getattr(caught, 'name', type(caught).__name__), message=getattr(caught, 'message', str(caught)),
        **(dict(code=caught.code) if hasattr(caught, 'code') else {}))


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0, str(root))
names = ('missing-provider', 'default-adapter', 'pending-register', 'pending-dispose', 'pending-config',
    'unconsumed-repeat', 'signal', 'foreign-replay', 'shared-replay', 'held-replay', 'new-current-owner')
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
