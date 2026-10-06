import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace


async def observe(name):
    from dsh.cordis.context import Context
    from dsh.llm.llm_service import LlmRuntime, LlmError
    from dsh.core.session import Session
    from dsh.compaction.native_summary import summarize
    from dsh.compaction.compaction_basic.config import resolve_config
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    class Adapter:
        async def prepare_call(self, provider, model, signal=None):
            return dict(model=dict(provider=provider, id=model, name=model), stream=self.stream)
        async def stream(self, request):
            if name == 'after-partial':
                yield dict(type='block-start', index=0, blockType='text')
                yield dict(type='text-delta', index=0, text='discarded')
            failure = LlmError('provider failed', 'SERVER', status=503, requestId='fixture-request')
            failure.__cause__ = OSError('socket closed')
            raise failure
    ctx.get('llm').register_adapter(['failure-probe'], Adapter())
    session = Session('summary-session')
    message = dict(role='user', content=[dict(type='text', text='important facts')], source=dict(kind='user'), id='fixture-message')
    chunks, stream_error, error = [], None, None
    try:
        try:
            async for chunk in ctx.get('llm').stream(dict(provider='failure-probe', model='probe', messages=[message])):
                chunks.append(chunk)
        except Exception as failure:
            stream_error = dict(name=getattr(failure, 'name', type(failure).__name__), message=getattr(failure, 'message', str(failure)), code=getattr(failure, 'code', None))
        try:
            engine = SimpleNamespace(ctx=ctx, config=resolve_config(dict(summarizationProvider='failure-probe', summarizationModel='probe', maxTokens=17)))
            agent = SimpleNamespace(session=session, options=SimpleNamespace(provider='failure-probe', model='probe'))
            await summarize(engine, dict(messages=[message]), agent, None)
        except Exception as failure:
            error = dict(name=getattr(failure, 'name', type(failure).__name__), message=getattr(failure, 'message', str(failure)), code=getattr(failure, 'code', None))
        return dict(name=name, chunks=chunks, error=error, **(dict(streamError=stream_error) if stream_error else {}))
    finally:
        await ctx.fiber.dispose()


arguments = argparse.ArgumentParser()
arguments.add_argument('--root', type=Path, required=True)
arguments.add_argument('--output', type=Path, required=True)
options = arguments.parse_args()
root = options.root.resolve()
sys.path.insert(0, str(root))
rows = [asyncio.run(observe(name)) for name in ('before-output', 'after-partial')]
modules = {}
for name, module in sorted(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if path and (name == 'dsh' or name.startswith('dsh.')):
        selected = Path(path).resolve()
        modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
with options.output.open('x', encoding='utf-8') as stream:
    json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, indent=2)
