"""Deterministic deadline/first-page observations for current inspect registry."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

MODES=['success','sync-success','timeout','failure-timeout','first-failure','invalid-timeout','invalid-success',
    'wrong-agent-failure','wrong-agent-success','late-success','offline','disconnect','no-gateway',
    'abort','pre-abort','abort-publish','dispose','notify-timeout','notify-dispose','manifest-replace','manifest-empty',
    'omitted','null','host','host-snapshot','publish-throw']


def manifest():
    return dict(id='Service',description='Test Service provider.',methods=[dict(name='listService',description='Inspect one service.',
        inputSchema=dict(type='object',properties=dict(service=dict(type='string')),additionalProperties=False),
        outputSchema=dict(type='object',properties=dict(name=dict(type='string')),required=['name']))])


def prepare(output):
    import json
    path=output/'inputs.json';path.write_text(json.dumps(MODES),encoding='utf-8');return [path]


class Clock:
    def __init__(self):self.pending={};self.next=0
    def later(self,delay,callback,*args,**kwargs):
        self.next+=1;key=self.next;clock=self
        class Handle:
            def cancel(self):clock.pending.pop(key,None)
        self.pending[key]=(callback,args,delay)
        return Handle()
    def fire(self):
        for key,(callback,args,_) in list(self.pending.items()):
            self.pending.pop(key,None);callback(*args)


async def flush():
    for _ in range(20):await asyncio.sleep(0)


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    from dsh.extensions import inspect_registry_current as module
    rows=[]
    for mode in MODES:
        ctx=Context();clock=Clock();loop=asyncio.get_running_loop();original=loop.call_later
        requests=[];resolved=[];logs=[];acks=[];tasks=[];controller=AbortController();agent=NS(id='owner')
        fiber=ctx.plugin(module.CurrentCordisInspectRegistryService,100);await fiber
        registry=ctx.get('cordisInspect');registry.syncClientManifest([manifest()])
        loop.call_later=clock.later
        online=[mode!='offline']
        if mode!='no-gateway':ctx.provide('typertGateway',NS(hasLiveClient=lambda:online[0]))
        ctx.on('cordis/inspect-query',lambda request:requests.append(request))
        ctx.on('cordis/inspect-query-resolved',lambda event:resolved.append(event['requestId']))
        def notify(_event):raise ValueError('notify failed')
        if mode.startswith('notify-'):ctx.on('cordis/inspect-query-resolved',notify)
        def capture(*args,**kwargs):logs.append([args[0],str(args[1])])
        module.print=capture
        try:
            async def result(waiting):
                try:return dict(value=await waiting)
                except Exception as error:return dict(error=str(error))
            def start(value=UNDEFINED):
                waiting=registry.query('client','Service','listService',value,agent,controller.signal)
                task=asyncio.create_task(result(waiting));tasks.append(task);return task
            def answer(data=None,owner=agent):
                return registry.resolveClientQuery(owner,requests[-1]['requestId'],dict(ok=True,data=dict(name='theme') if data is None else data))
            if mode=='sync-success':ctx.on('cordis/inspect-query',lambda request:acks.append(registry.resolveClientQuery(agent,request['requestId'],dict(ok=True,data=dict(name='sync')))))
            if mode=='abort-publish':ctx.on('cordis/inspect-query',lambda request:controller.abort(ValueError('fixture abort')))
            if mode=='publish-throw':
                def failed(_):raise ValueError('publish failed')
                ctx.on('cordis/inspect-query',failed)
            if mode=='pre-abort':controller.abort(ValueError('fixture abort'))
            if mode in ('host','host-snapshot'):
                data=dict(name='local')
                registry.register(dict(manifest=manifest(),query=lambda *_:data))
                tasks.append(asyncio.create_task(result(registry.query('host','Service','listService',{},agent,controller.signal))))
                if mode=='host-snapshot':data['name']='mutated'
            else:start(None if mode=='null' else UNDEFINED)
            initial=dict(requests=len(requests),timers=len(clock.pending),pending=len(registry._pending))
            if mode in ('success','no-gateway','omitted','null'):acks.extend([answer(),answer()])
            elif mode in ('failure-timeout','first-failure'):
                acks.append(registry.resolveClientQuery(agent,requests[-1]['requestId'],dict(ok=False,reason='provider-error',message='page failed')))
                if mode=='first-failure':acks.append(registry.resolveClientQuery(agent,requests[-1]['requestId'],dict(ok=False,reason='provider-error',message='second failure')))
                clock.fire()
            elif mode in ('invalid-timeout','invalid-success'):
                acks.append(answer({}))
                if mode=='invalid-success':acks.append(answer())
                else:clock.fire()
            elif mode.startswith('wrong-agent'):
                resolution=dict(ok=False,reason='provider-error',message='foreign page') if mode.endswith('failure') else dict(ok=True,data=dict(name='foreign'))
                acks.append(registry.resolveClientQuery(NS(id='other'),requests[-1]['requestId'],resolution));clock.fire()
            elif mode in ('timeout','notify-timeout'):clock.fire()
            elif mode=='late-success':clock.fire();acks.append(answer())
            elif mode=='disconnect':online[0]=False;clock.fire()
            elif mode=='abort':controller.abort(ValueError('fixture abort'))
            elif mode in ('dispose','notify-dispose'):await fiber.dispose()
            elif mode in ('manifest-replace','manifest-empty'):
                changed=manifest();changed['methods'][0]['outputSchema']=dict(type='object',properties=dict(next=dict(type='string')),required=['next'])
                registry.syncClientManifest([] if mode=='manifest-empty' else [changed]);acks.append(answer())
                if mode=='manifest-replace':start();acks.append(answer(dict(next='new')))
            await flush()
            results=[await task for task in tasks]
            rows.append(dict(mode=mode,initial=initial,requests=requests,resolved=resolved,acks=acks,results=results,
                timers=len(clock.pending),pending=len(registry._pending),listeners=len(controller.signal._listeners),logs=logs))
        finally:
            registry.close();await flush();loop.call_later=original
            del module.print
            await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_inspect_registry.mts',prepare=prepare,
        scope='Deterministic actual Source/current Native registry client deadlines, live-gateway check, first valid response/failure retention, ownership/abort/disposal, eager publication and host snapshot await boundary. Clock and Gateway liveness are controlled; original Source tests cover actual Gateway streams separately.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/extensions/inspect_registry_current.py'])
