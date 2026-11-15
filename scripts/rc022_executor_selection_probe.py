"""Pair executor selection, prompt ownership and retained dispatch."""
import asyncio
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.scope import create_scope
    from dsh.core.system_prompt import SystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    rows=[]
    for action in ('missing','duplicate','root-unload','scoped-unload','scoped-replace','inherited','accepted','sections'):
        ctx=Context()
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(CurrentToolsPlugin)
        tools=ctx.tools
        class Owner(Plugin):
            inject=['tools','systemPrompt']
            def apply(self,scope):
                owners.append(scope)
        owners=[]
        root_owner=await ctx.plugin(Owner)
        class Agent:
            pass
        agent,child=Agent(),Agent()
        scope=create_scope(owners[0],agent);agent.ctx=scope.ctx
        child_scope=create_scope(owners[0],child,agent);child.ctx=child_scope.ctx
        gate=asyncio.Event();started=asyncio.Event();accepted=None
        class Executor:
            def __init__(self,name):
                self.name=name
                self.sections=[dict(name='fixture-'+name,order=123,text=lambda definitions:name+':'+','.join(item.name for item in definitions))]
            def describe(self,definitions):
                return dict(schemas=[dict(name=self.name,description='',parameters=dict(type='object'))])
            async def execute(self,input):
                started.set()
                if action=='accepted':await gate.wait()
                return dict(provider=self.name,same=input is request)
        request=dict(calls=[],agent=agent,signal=None)
        row=dict(action=action)
        async def dispatch(target=agent):
            try:
                value=dict(request,agent=target)
                if target is agent:value=request
                return await tools.execute(value)
            except Exception as error:return dict(code=error.code)
        try:
            root=Executor('root')
            if action!='missing':owners[0].tools.setExecutor(root)
            if action=='duplicate':
                try:tools.setExecutor(Executor('duplicate'))
                except Exception as error:row['duplicate']=str(error)
            if action in ('scoped-unload','scoped-replace','inherited','sections'):
                scope.ctx.tools.setExecutor(Executor('local'))
            if action=='accepted':
                accepted=asyncio.ensure_future(dispatch())
                await started.wait()
                await root_owner.dispose()
                row['during']=await dispatch()
                gate.set();row['accepted']=await accepted
            elif action=='root-unload':await root_owner.dispose()
            elif action in ('scoped-unload','scoped-replace'):
                await scope.dispose()
                row['unloaded']=await dispatch()
                if action=='scoped-replace':
                    replacement=create_scope(owners[0],agent)
                    agent.ctx=replacement.ctx
                    replacement.ctx.tools.setExecutor(Executor('replacement'))
            row['dispatch']=await dispatch(child if action=='inherited' else agent)
            if action=='sections':
                assembly=await ctx.systemPrompt.assemble(dict(scope=agent))
                row['sections']=[dict(name=item['name'],text=item['text']) for item in assembly['sections'] if item['name'].startswith('fixture-')]
                row['schemas']=[item['name'] for item in assembly['tools']]
            rows.append(row)
        finally:
            gate.set()
            if accepted is not None:await asyncio.gather(accepted,return_exceptions=True)
            await ctx.fiber.dispose()
    for action in ('register-rollback','register-nesting'):
        ctx=Context();await ctx.plugin(SystemPrompt);await ctx.plugin(CurrentToolsPlugin)
        tools=ctx.tools;row=dict(action=action);trace=[]
        definition=dict(name='echo',description='',parameters=dict(type='object'),output=dict(schema=dict(type='string'),render=lambda a,v:[]),execute=lambda a,e:'ok')
        if action=='register-rollback':
            failed=[]
            def changed():
                if not failed:
                    failed.append(True)
                    raise RuntimeError('change failed')
            remove=ctx.on('tools/change',changed)
            try:tools.register(definition)
            except Exception as error:row['error']=str(error)
            row['leaked']=tools.get('echo') is not None
            remove();dispose=tools.register(definition);row['retry']=tools.get('echo') is not None;dispose()
        else:
            class Nested(Plugin):
                inject=['tools']
                def apply(self,scope):
                    async def first():
                        await asyncio.sleep(0)
                        trace.append(scope.tools.get('echo') is not None)
                    def lifecycle():
                        yield lambda:trace.append('last')
                        yield scope.tools.register(definition)
                        yield first
                    scope.effect(lifecycle)
            owner=await ctx.plugin(Nested);await owner.dispose();row['trace']=trace;row['remaining']=tools.get('echo') is not None
        rows.append(row);await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_executor_selection.mts','Scoped executor selection, missing/unloaded tombstones, replacement, inherited selection, prompt sections and accepted provider lifetime.',[Path(__file__).resolve(),ROOT/'dsh/core/tools.py'])
