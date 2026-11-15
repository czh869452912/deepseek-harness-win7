"""Pair service admission and scoped provider registration around the real projection registry."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.session.json import UNDEFINED
    from dsh.subagent.service import SubagentPlugin
    rows=[]
    for action in ('local','external','no-provider','no-methods','duplicate','added-failure','removed','provider-change',
                   'reserved-external','capability','fork-preset','stale-parent','invalid-depth','invalid-schema','no-agents'):
        ctx=Context();store=CurrentSessionStore(ctx,4);registry=SessionProjectionRegistry(ctx,4)
        ctx.set_service('workingDirectory',NS())
        parent=NS(id='parent')
        if action!='no-agents':ctx.set_service('agents',NS(get=lambda identity:parent if identity=='parent' else None,list=lambda:[]))
        trace=[]
        ctx.on('subagent/provider-added',lambda provider:trace.append('added:'+provider.name))
        ctx.on('subagent/provider-removed',lambda name:trace.append('removed:'+name))
        owner=await ctx.plugin(SubagentPlugin)
        service=ctx.get('subagents');original=service.manager
        row=dict(action=action,depth=service.resolveMaxDepth(),capacity=service.setting('maxActiveSubagents'),
                 managed=service.resolveMaxDepth('provider-managed') is UNDEFINED,
                 projections=sorted(registry.snapshot(store.create('session'))['values']))
        async def prepare(request):trace.append('prepared');return {}
        async def external(request):trace.append('started');return {}
        provider=NS(name='test',capabilities=dict(agentOptions=True,agentPreset=True,outputSchema=True,depthLimit=True),inheritsParentContext=False)
        if action in ('external','reserved-external'):provider.start=external
        elif action!='no-methods':provider.prepareContinuable=prepare
        spec=dict(provider='test',parent=parent,prompt=[],label='Task',signal=NEVER_ABORTED,delivery='caller')
        dispose=None
        try:
            if action=='added-failure':
                def fail(value):raise RuntimeError('listener failure')
                ctx.on('subagent/provider-added',fail)
            if action!='no-provider':dispose=service.registerProvider(provider)
            if action=='duplicate':service.registerProvider(provider)
            elif action=='removed':dispose();dispose()
            elif action=='reserved-external':spec['childId']='reserved'
            elif action=='capability':provider.capabilities['agentOptions']=False;spec['agentOptions']={}
            elif action=='fork-preset':provider.inheritsParentContext=True;spec['agentPreset']='coding'
            elif action=='stale-parent':spec['parent']=NS(id='parent')
            elif action=='invalid-depth':spec['maxDepth']=-1
            elif action=='invalid-schema':spec['outputSchema']=dict(type='array',items=dict(type='string'))
            async def local(spec,checked):
                trace.append('local')
                if action=='provider-change':
                    dispose()
                    service.registerProvider(NS(name='test',capabilities={},prepareContinuable=prepare))
                await checked({})
                return dict(kind='local')
            async def remote(spec,checked):trace.append('external');await checked({});return dict(kind='external')
            if action!='no-agents':service.manager=NS(start_local=local,start_external=remote)
            row['value']=await service.startActivation(spec)
        except Exception as error:row['error']=getattr(error,'code',None)
        finally:
            service.manager=original
            row['registered']=service.getProvider('test') is not None
            await owner.dispose()
            row['released']=ctx.get('subagents') is None
            row['remaining']=sorted(registry.snapshot(store.get('session'))['values'])
            row['trace']=trace
            await ctx.fiber.dispose()
        rows.append(row)
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_subagent_service.mts','Real async projection/service registration with controlled manager dispatch, provider effects/rollback and replacement identity, capabilities, parent identity and volatile default settings.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/service.py',ROOT/'dsh/subagent/providers.py'])
