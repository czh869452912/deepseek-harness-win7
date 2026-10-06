import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys


async def observe(name):
    from dsh.cordis.context import Context
    from dsh.llm.llm_service import LlmRuntime
    ctx=Context()
    await ctx.plugin(LlmRuntime)
    closed,chunks=[],[]
    next_calls=0
    class Iterator:
        def __aiter__(self):
            return self
        async def __anext__(self):
            nonlocal next_calls
            next_calls+=1
            if name.startswith('reject'):
                raise RuntimeError('iterator failed')
            if name.startswith('eof'):
                if next_calls==1:
                    return dict(type='finish',reason=dict(kind='stop'))
                raise StopAsyncIteration
            return dict(type='text-delta',index=0,text='partial')
    class Closable(Iterator):
        async def aclose(self):
            closed.append('closed')
            if name.endswith('cleanup-error'):
                raise RuntimeError('cleanup failed')
    class Adapter:
        async def prepare_call(self,provider,model,signal=None):
            return dict(model=dict(provider=provider,id=model,name=model),stream=self.stream)
        def stream(self,options):
            return Iterator() if name=='close-no-return' else Closable()
    ctx.get('llm').register_adapter(['fixture'],Adapter())
    stream=ctx.get('llm').stream(dict(provider='fixture',model='model',messages=[]))
    error=None
    try:
        try:
            try:
                async for chunk in stream:
                    chunks.append(chunk)
                    if name.startswith('close'):
                        break
            finally:
                await stream.aclose()
        except Exception as caught:
            error=dict(name='Error' if isinstance(caught,RuntimeError) else type(caught).__name__,message=str(caught))
        return dict(name=name,nextCalls=next_calls,chunks=chunks,closed=closed,**(dict(error=error) if error else {}))
    finally:
        await ctx.fiber.dispose()


parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
arguments=parser.parse_args()
root=arguments.root.resolve()
sys.path.insert(0,str(root))
rows=[asyncio.run(observe(name)) for name in ('reject','reject-cleanup-error','eof','eof-cleanup-error','close','close-cleanup-error','close-no-return')]
modules={}
for name,module in sorted(sys.modules.items()):
    path=getattr(module,'__file__',None)
    if path and (name=='dsh' or name.startswith('dsh.')):
        selected=Path(path).resolve()
        modules[selected.relative_to(root).as_posix()]=hashlib.sha256(selected.read_bytes()).hexdigest()
with arguments.output.open('x',encoding='utf-8') as stream:
    json.dump(dict(root=str(root),executable=sys.executable,python=sys.version,modules=modules,rows=rows),stream,indent=2)
    stream.write('\n')
