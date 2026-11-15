"""Pair factory slot identity and caller tracing without constructing a loop."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.cordis.service import Service
    from dsh.cordis.utils import symbols
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    rows=[]
    for action in ('missing','plain','traced','duplicate','owner-replace','closing-slot'):
        ctx=Context();row=dict(action=action);release=asyncio.Event();started=asyncio.Event();closing=None
        requests=dict(create=dict(sessionId='new'),resume=dict(resumeSessionId='old'));handles=dict(create=object(),resume=object());calls=[];caller=[]
        class Plain:
            async def createAgent(self,owner,request):calls.append(dict(kind='create',request=request is requests['create'],owner=owner.fiber is caller[0]));return handles['create']
            async def resume(self,owner,request):calls.append(dict(kind='resume',request=request is requests['resume'],owner=owner.fiber is caller[0]));return handles['resume']
        states={};raw=[]
        class Factory(Service):
            def __init__(self,scope):super().__init__(scope,'tracedFactory');states[id(self)]=[];raw.append(self)
            def record(self,kind,owner,request):
                original=getattr(self,symbols.original,None) or self
                states[id(original)].append(kind)
                calls.append(dict(kind=kind,request=request is requests[kind],owner=owner.fiber is caller[0],receiver=self.ctx.fiber is caller[0],canonical=original is raw[0]))
            async def createAgent(self,owner,request):self.record('create',owner,request);return handles['create']
            async def resume(self,owner,request):self.record('resume',owner,request);return handles['resume']
        try:
            await ctx.plugin(Registry);await ctx.plugin(CurrentAgentPlugin);agents=ctx.get('agents');factory=Plain()
            if action=='missing':
                for kind in ('create','resume'):
                    try:await getattr(agents,kind)(requests[kind])
                    except Exception as error:row[kind]=str(error)
            elif action in ('plain','traced'):
                if action=='traced':await ctx.plugin(Factory);factory=ctx.get('tracedFactory')
                agents.setFactory(factory)
                class Caller(Plugin):
                    inject=['agents']
                    async def apply(self,scope):
                        caller.append(scope.fiber)
                        row['createSame']=await scope.get('agents').create(requests['create']) is handles['create']
                        row['resumeSame']=await scope.get('agents').resume(requests['resume']) is handles['resume']
                owner=await ctx.plugin(Caller);row['calls']=calls
                if action=='traced':row['rawCalls']=states[id(raw[0])]
                await owner.dispose();row['slotRetained']=agents._factory is not None
            elif action=='duplicate':
                dispose=agents.setFactory(factory)
                try:agents.setFactory(Plain())
                except Exception as error:row['error']=str(error)
                row['same']=agents._factory is factory;dispose();row['repeat']=dispose() is None;row['cleared']=agents._factory is None
            else:
                owners=[]
                class Owner(Plugin):
                    inject=['agents']
                    def apply(self,scope):
                        owners.append(scope);slot=scope.get('agents').setFactory(factory)
                        if action=='owner-replace':return
                        async def drain():started.set();await release.wait()
                        def lifecycle():yield slot;yield drain
                        scope.effect(lifecycle,'factory slot lifetime')
                owner=await ctx.plugin(Owner);row['retained']=agents._factory is factory;closing=asyncio.ensure_future(owner.dispose())
                if action=='closing-slot':
                    await started.wait()
                    try:agents.setFactory(Plain())
                    except Exception as error:row['closingDuplicate']=str(error)
                release.set();await closing;row['cleared']=agents._factory is None
                replacement=Plain();dispose=agents.setFactory(replacement);row['replacement']=agents._factory is replacement;dispose()
            rows.append(row)
        finally:
            release.set()
            if closing is not None:await asyncio.gather(closing,return_exceptions=True)
            await ctx.fiber.dispose()
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_factory_slot.mts','Factory call owner/request/result identity; canonical Service tracing; occupied and closing slot rejection; exact factory effect nesting and owner replacement.',[Path(__file__).resolve(),ROOT/'dsh/core/agent_current.py',ROOT/'dsh/core/agent_loop_current.py'])
