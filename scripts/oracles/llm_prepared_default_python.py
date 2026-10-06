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
    trace, chunks = [], []
    pending, ready = asyncio.Event(), asyncio.Event()
    class Adapter:
        async def resolve_model(self,provider,identifier):
            trace.append(dict(kind='resolve'))
            if name == 'pending-default-stream':
                ready.set()
                await pending.wait()
            return dict(provider=provider,id=identifier,name=identifier)

        async def stream(self,options):
            trace.append(dict(kind='first'))
            yield dict(type='finish',reason=dict(kind='stop'))
    adapter = Adapter()
    ctx.get('llm').register_adapter(['fixture'],adapter)
    async def middleware(options,next):
        trace.append(dict(kind='middleware'))
        return await next()
    ctx.on('llm/stream',middleware)
    async def replacement(options):
        trace.append(dict(kind='second'))
        yield dict(type='finish',reason=dict(kind='stop'))
    prepared, error = None, None
    config = dict(provider='fixture',model='model')
    try:
        preparing = asyncio.create_task(ctx.get('llm').prepareCall(config))
        if name == 'pending-default-stream':
            await ready.wait()
            adapter.stream = replacement
            pending.set()
        prepared = await preparing
        if name == 'late-default-stream':
            adapter.stream = replacement
        async for chunk in prepared['stream'](dict(prepared.get('config',config),messages=[])):
            chunks.append(chunk)
    except Exception as caught:
        error = dict(name=getattr(caught,'name',type(caught).__name__),message=getattr(caught,'message',str(caught)),
            **(dict(code=caught.code) if hasattr(caught,'code') else {}))
    finally:
        pending.set()
        await ctx.fiber.dispose()
    return dict(name=name,trace=trace,chunks=chunks,**(dict(config=prepared['config']) if prepared is not None and 'config' in prepared else {}),
        **(dict(error=error) if error is not None else {}))


parser = argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0,str(root))
rows = [asyncio.run(observe(name)) for name in ('late-default-stream','pending-default-stream')]
modules = {}
for name,module in sorted(sys.modules.items()):
    source = getattr(module,'__file__',None)
    if source and (name == 'dsh' or name.startswith('dsh.')):
        path = Path(source).resolve()
        modules[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
with arguments.output.open('x',encoding='utf-8') as stream:
    json.dump(dict(root=str(root),executable=sys.executable,python=sys.version,modules=modules,rows=rows),stream,indent=2)
    stream.write('\n')
