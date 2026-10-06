import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys


NAMES = ('plain', 'primitive', 'empty-primitive', 'null-primitive', 'hostile-primitive', 'harness', 'llm',
    'foreign-code', 'foreign-valid', 'foreign-mismatch', 'foreign-empty-id', 'accessor-code', 'accessor-failure', 'accessor-message', 'foreign-null-status', 'foreign-null-retry', 'foreign-null-id')


def failure(name):
    from dsh.cordis.errors import ThrownValueError
    from dsh.llm.error import HarnessError
    from dsh.llm.llm_service import LlmError
    if name in ('primitive', 'empty-primitive', 'null-primitive'):
        return ThrownValueError('plain failure' if name == 'primitive' else '' if name == 'empty-primitive' else None)
    if name == 'hostile-primitive':
        class Hostile:
            def __str__(self):
                raise RuntimeError('coercion failed')
        return ThrownValueError(Hostile())
    if name == 'harness':
        return HarnessError('owned failure', 'OWNED')
    if name == 'llm':
        error = LlmError('provider failed', 'SERVER', status=503, providerRetryAfterMs=50, requestId='fixture-request')
        error.__cause__ = OSError('socket closed')
        return error
    class Foreign(RuntimeError):
        pass
    error = Foreign('provider failed')
    if name in ('accessor-code', 'accessor-failure', 'accessor-message', 'foreign-null-status', 'foreign-null-retry', 'foreign-null-id'):
        attribute = name.split('-')[1]
        def getter(self):
            raise RuntimeError(attribute + ' getter failed')
        setattr(Foreign, attribute, property(getter))
    if name in ('foreign-code', 'foreign-valid', 'foreign-mismatch', 'foreign-empty-id'):
        error.code = 'FOREIGN'
    if name in ('foreign-valid', 'foreign-mismatch', 'foreign-empty-id', 'accessor-code'):
        error.failure = dict(message='carried failure', code='OTHER' if name == 'foreign-mismatch' else 'FOREIGN')
    if name.startswith('foreign-null-'):
        error.code = 'FOREIGN'
        error.failure = dict(message='carried failure', code='FOREIGN')
        error.failure[{'status': 'status', 'retry': 'providerRetryAfterMs', 'id': 'requestId'}[name[13:]]] = None
    if name == 'foreign-valid':
        error.failure.update(status=429, providerRetryAfterMs=25, requestId='foreign-request')
    if name == 'foreign-empty-id':
        error.failure['requestId'] = ''
    return error


async def observe(name, phase):
    from dsh.cordis.context import Context
    from dsh.llm.llm_service import LlmRuntime
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    error = failure(name)
    class Adapter:
        async def prepare_call(self, provider, model, signal=None):
            return dict(model=dict(provider=provider, id=model, name=model), stream=self.stream)
        def stream(self, request):
            if phase == 'dispatch':
                raise error
            async def produce():
                if phase == 'after-partial':
                    yield dict(type='text-delta', index=0, text='partial')
                raise error
            return produce()
    ctx.get('llm').register_adapter(['fixture'], Adapter())
    chunks, thrown = [], None
    try:
        try:
            async for chunk in (await ctx.get('llm').prepareCall(dict(provider='fixture', model='model'))).get('stream')(dict(provider='fixture', model='model', messages=[])):
                chunks.append(chunk)
        except Exception as caught:
            try:
                message = str(caught)
            except Exception:
                message = 'unrenderable observer exception'
            thrown = dict(name=type(caught).__name__, message=message)
        return dict(name=name + '/' + phase, chunks=chunks, **(dict(error=thrown) if thrown else {}))
    finally:
        await ctx.fiber.dispose()


async def observe_ownership(name):
    from dsh.cordis.context import Context
    from dsh.llm.llm_service import LlmRuntime
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    closed = []
    class Adapter:
        async def prepare_call(self, provider, model, signal=None):
            return dict(model=dict(provider=provider, id=model, name=model), stream=self.stream)
        async def stream(self, request):
            try:
                yield dict(type='text-delta', index=0, text='partial')
                yield dict(type='finish', reason=dict(kind='stop'))
            finally:
                closed.append('closed')
    ctx.get('llm').register_adapter(['fixture'], Adapter())
    async def middleware(options, next_fn):
        if name == 'middleware-before':
            raise RuntimeError('middleware failed')
        stream = await next_fn()
        try:
            async for chunk in stream:
                yield chunk
                raise RuntimeError('middleware failed')
        finally:
            await stream.aclose()
    if name.startswith('middleware'):
        ctx.on('llm/stream', middleware)
    chunks, error = [], None
    stream = (await ctx.get('llm').prepareCall(dict(provider='fixture', model='model'))).get('stream')(dict(provider='fixture', model='model', messages=[]))
    try:
        try:
            async for chunk in stream:
                chunks.append(chunk)
                if name == 'consumer':
                    raise RuntimeError('consumer failed')
        except Exception as caught:
            error = dict(name='Error' if type(caught) is RuntimeError else type(caught).__name__, message=str(caught))
        finally:
            await stream.aclose()
        return dict(name=name, chunks=chunks, error=error, closed=closed)
    finally:
        await ctx.fiber.dispose()


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0, str(root))
rows = [asyncio.run(observe(name, phase)) for name in NAMES for phase in ('dispatch', 'iterate', 'after-partial')]
rows.extend(asyncio.run(observe_ownership(name)) for name in ('middleware-before', 'middleware-after', 'consumer'))
modules = {}
for name, module in sorted(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if path and (name == 'dsh' or name.startswith('dsh.')):
        selected = Path(path).resolve()
        modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
with arguments.output.open('x', encoding='utf-8') as stream:
    json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, indent=2)
