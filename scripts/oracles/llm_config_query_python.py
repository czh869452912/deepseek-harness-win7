import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
arguments=parser.parse_args()
root=arguments.root.resolve()
sys.path.insert(0,str(root))
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.llm.llm_service import LlmRuntime


async def observe(name):
    ctx=Context()
    await ctx.plugin(LlmRuntime)
    trace=[]
    signal=AbortController().signal
    pending,ready=asyncio.Event(),asyncio.Event()
    defaults=name in ('defaults','override','null-with-default')
    class Adapter:
        def __init__(self,generation):
            self.generation=generation
        async def resolve_model(self,provider,model,selected_signal=None):
            trace.append(dict(kind='resolve',generation=self.generation,provider=provider,id=model,signalSame=selected_signal is signal))
            if name.startswith('pending-'):
                ready.set()
                await pending.wait()
            info=dict(provider=provider,id=model,name=model)
            if defaults:
                info.update(defaultMaxTokens=4096,reasoning=dict(efforts=[dict(id='low',name='Low'),dict(id='high',name='High')],defaultEffort='low'))
            return info
        async def prepare_call(self,provider,model,selected_signal=None):
            trace.append(dict(kind='prepare',generation=self.generation,provider=provider,id=model,signalSame=selected_signal is signal))
            return dict(model=dict(provider=provider,id=model,name=model,defaultMaxTokens=7),stream=self.stream)
        async def stream(self,options):
            trace.append(dict(kind='unexpected-stream'))
            yield dict(type='finish',reason=dict(kind='stop'))
    if name!='no-adapter':
        ctx.get('llm').register_adapter(['fixture'],Adapter('first'))
    config=dict(provider='fixture',model='model',stop=['done'],extra=dict(value=1))
    if name=='override':
        config.update(maxTokens=128,reasoningEffort='high')
    if name=='unsupported':
        config['reasoningEffort']='invalid'
    if name.startswith('null-'):
        config['reasoningEffort']=None
    try:
        querying=asyncio.create_task(ctx.get('llm').resolveCallConfig(config,signal))
        if name.startswith('pending-'):
            entered=asyncio.create_task(ready.wait())
            await asyncio.wait_for(asyncio.wait((entered,querying),return_when=asyncio.FIRST_COMPLETED),3)
            if not entered.done():
                entered.cancel()
                await asyncio.gather(entered,return_exceptions=True)
            if ready.is_set():
                if name=='pending-replace':
                    ctx.get('llm').register_adapter(['fixture'],Adapter('second'))
                else:
                    config['model']='changed-model'
            pending.set()
        result=await querying
        observed=dict(result=copy.deepcopy(result),same=result is config,sameStop=result['stop'] is config['stop'],input=copy.deepcopy(config))
        result['model']='result-write'
        observed['inputAfterResultChange']=copy.deepcopy(config)
    except Exception as error:
        observed=dict(error=dict(name=getattr(error,'name',type(error).__name__),message=getattr(error,'message',str(error)),**(dict(code=error.code) if hasattr(error,'code') else {})),input=copy.deepcopy(config))
    finally:
        pending.set()
        await ctx.fiber.dispose()
    return dict(name=name,trace=trace,observed=observed)


names=('plain','defaults','override','custom-prepare','no-adapter','unsupported','null-with-default','null-without-reasoning','pending-replace','pending-input')
rows=[asyncio.run(observe(name)) for name in names]
modules={}
for name,module in sorted(sys.modules.items()):
    source=getattr(module,'__file__',None)
    if source and (name=='dsh' or name.startswith('dsh.')):
        path=Path(source).resolve()
        modules[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
with arguments.output.open('x',encoding='utf-8') as stream:
    json.dump(dict(root=str(root),executable=sys.executable,python=sys.version,modules=modules,rows=rows),stream,indent=2)
    stream.write('\n')
