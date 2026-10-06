import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


async def observe(name):
    from dsh.cordis.context import Context
    from dsh.llm.llm_service import LlmRuntime
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    service = ctx.get('llm')
    trace,requests,chunks = [],[],[]
    class Adapter:
        async def prepare_call(self,provider,model,signal=None):
            trace.append(dict(kind='prepare',provider=provider,model=model))
            if name=='prepare-error':
                raise RuntimeError('preparation failed')
            info = dict(provider='foreign' if name=='prepare-invalid-model' else provider,id=model,name=model)
            if name in ('default-config','invalid-max','invalid-reasoning','route-before-prepare'):
                info.update(defaultMaxTokens=256,reasoning=dict(efforts=[dict(id='low',name='Low'),dict(id='high',name='High')],defaultEffort='low'))
            if name=='projection-text':
                info['inputModalities']=['text']
            return dict(model=info,stream=self.stream)
        async def stream(self,options):
            trace.append(dict(kind='dispatch',provider=options['provider'],model=options['model']))
            requests.append(options)
            yield dict(type='finish',reason=dict(kind='stop'))
    if name!='unknown':
        service.register_adapter(['fixture'],Adapter())
    async def middleware(options,next):
        trace.append(dict(kind='middleware',provider=options['provider'],model=options['model'],messages=copy.deepcopy(options['messages'])))
        if name=='route-before-prepare':
            options['provider']='fixture'
        return await next()
    ctx.on('llm/stream',middleware)
    def legacy_guard(*arguments,**keywords):
        trace.append(dict(kind='legacy-fallback'))
        raise RuntimeError('controlled legacy fallback admission')
    service.chat_completion_stream=legacy_guard
    options=dict(provider='missing' if name=='unknown' else 'initial' if name=='route-before-prepare' else 'fixture',model='model',messages=[])
    if name=='invalid-max':
        options['maxTokens']=0
    if name=='invalid-reasoning':
        options['reasoningEffort']='unsupported'
    if name.startswith('projection'):
        options['messages']=[dict(id='image-message',role='user',content=[dict(type='image',attachment=dict(attachmentId='sha256:'+'a'*64,mediaType='image/png',bytes=3,width=1,height=1))],source=dict(kind='user'))]
    error=None
    try:
        try:
            async for chunk in service.stream(options):
                chunks.append(chunk)
        except Exception as caught:
            error=dict(name='Error' if isinstance(caught,RuntimeError) else type(caught).__name__,message=str(caught),**(dict(code=caught.code) if hasattr(caught,'code') else {}))
        return dict(name=name,trace=trace,requests=requests,chunks=chunks,**(dict(error=error) if error else {}))
    finally:
        await ctx.fiber.dispose()


parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
arguments=parser.parse_args()
root=arguments.root.resolve()
sys.path.insert(0,str(root))
rows=[asyncio.run(observe(name)) for name in ('unknown','prepare-error','prepare-invalid-model','default-config','invalid-max','invalid-reasoning','route-before-prepare','projection-unknown','projection-text')]
modules={}
for name,module in sorted(sys.modules.items()):
    path=getattr(module,'__file__',None)
    if path and (name=='dsh' or name.startswith('dsh.')):
        selected=Path(path).resolve()
        modules[selected.relative_to(root).as_posix()]=hashlib.sha256(selected.read_bytes()).hexdigest()
with arguments.output.open('x',encoding='utf-8') as stream:
    json.dump(dict(root=str(root),executable=sys.executable,python=sys.version,modules=modules,rows=rows),stream,indent=2)
    stream.write('\n')
