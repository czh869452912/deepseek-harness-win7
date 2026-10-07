import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


async def observe(name):
    from dsh.cordis.context import Context
    from dsh.core.agent_loop import AgentLoopPlugin
    from dsh.core.agent import AgentPlugin
    from dsh.core.session import SessionPlugin
    from dsh.core.agent import AgentOptions
    from dsh.core.system_prompt import SystemPrompt
    from dsh.core.tools import ToolsPlugin
    from dsh.core.session.json import FrozenDict
    from dsh.llm.agent_request import is_agent_loop_request
    from dsh.llm.llm_service import LlmRuntime
    ctx = Context()
    for plugin in (LlmRuntime,ToolsPlugin,SystemPrompt,SessionPlugin, AgentPlugin, AgentLoopPlugin):
        await ctx.plugin(plugin)
    trace, requests = [], []
    parent = None
    request_signal = None
    dispose = lambda: None
    def snapshot(options):
        signal = options.get('signal')
        result = dict(options)
        result['signal'] = dict(present=False) if signal is None else dict(present=True,
            same=signal is request_signal,aborted=signal.aborted,
            canThrow=callable(getattr(signal,'throwIfAborted',None)))
        return result
    class Adapter:
        def __init__(self,generation):
            self.generation = generation

        async def prepare_call(self,provider,model,signal=None):
            trace.append(dict(kind='prepare',generation=self.generation,provider=provider,model=model,
                signalPresent=signal is not None,signalSame=signal is request_signal,
                aborted=signal.aborted if signal is not None else None))
            if name == 'registration-switch' and self.generation == 'first':
                dispose()
                ctx.get('llm').register_adapter(['fixture'],Adapter('second'))
            return dict(model=dict(provider=provider,id=model,name=model,context=dict(contextWindow=100),
                defaultMaxTokens=256,reasoning=dict(efforts=[dict(id='low',name='Low'),dict(id='high',name='High')],defaultEffort='low')),
                stream=self.dispatch)

        async def dispatch(self,options):
            requests.append(dict(generation=self.generation,request=snapshot(options),
                frozen=isinstance(options,FrozenDict),marked=is_agent_loop_request(options)))
            yield dict(type='finish',reason=dict(kind='stop'))

        async def stream(self,options):
            raise RuntimeError('unprepared adapter dispatch forbidden')
            yield None
    if name != 'missing-middleware':
        dispose = ctx.get('llm').register_adapter(['fixture'],Adapter('first'))
    async def request(data,next):
        nonlocal request_signal
        request_signal = data.get("signal")
        config = await next()
        return dict(config,maxTokens=128,reasoningEffort='low') if name == 'request-overrides' else config
    ctx.on('agent/request',request)
    async def finish():
        yield dict(type='finish',reason=dict(kind='stop'))
    async def middleware(options,next):
        trace.append(dict(kind='middleware',request=snapshot(options),frozen=isinstance(options,FrozenDict),
            marked=is_agent_loop_request(options)))
        return finish() if name == 'missing-middleware' else await next()
    ctx.on('llm/stream',middleware)
    parent = await ctx.get('agent_loop').create('prepared-agent',options=AgentOptions(provider='fixture',model='model',
        max_tokens=64 if name == 'request-overrides' else None,reasoning_effort='high' if name == 'request-overrides' else None))
    try:
        parent.agent.followup('prepared request')
        await asyncio.wait_for(parent.agent.when_idle(),10)
        return dict(name=name,trace=trace,requests=requests,
            events=[dict(type=event['type'],data=copy.deepcopy(event['data'])) for event in parent.agent.session.events],
            messages=parent.agent.session.derive_messages())
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()


parser = argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0,str(root))
names = ('defaults','request-overrides','signal','registration-switch','missing-middleware')
rows = [asyncio.run(observe(name)) for name in names]
modules = {}
for name,module in sorted(sys.modules.items()):
    source = getattr(module,'__file__',None)
    if source and (name == 'dsh' or name.startswith('dsh.')):
        path = Path(source).resolve()
        modules[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
with arguments.output.open('x',encoding='utf-8') as stream:
    json.dump(dict(root=str(root),executable=sys.executable,python=sys.version,modules=modules,rows=rows),stream,indent=2)
    stream.write('\n')
