"""Pair retained declarative presets through actual factories and delegation."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from dsh.cordis.loader import Loader
    from dsh.core.scope import create_scope,ScopeKey
    from dsh.core.tools import ToolExecutionInput
    from dsh.presets.registry_current import CurrentAgentPresetRegistry, CurrentAgentPreset
    from dsh.subagent.delegation_tool import SubagentDelegationTool
    from scripts.rc022_subagent_fixture import setup
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];agents=[]
    def contribution(ctx,config):
        name=config['tool']
        ctx.get('tools').register(dict(name=name,description='fixture tool '+name,parameters=dict(type='object',properties={},additionalProperties=False),
            execute=lambda *_:name,output=dict(schema=dict(type='string'),render=lambda _,value:[dict(type='text',text=value)])))
        ctx.get('systemPrompt').section(dict(name='preset:'+name,order=10,text='section for '+name))
    contribution.inject=['tools','systemPrompt']
    try:
        ctx.baseUrl=(workspace or WORKSPACE).as_uri()+'/'
        await ctx.plugin(Loader)
        ctx.loader.builtins['contribute']=contribution
        await ctx.plugin(CurrentAgentPresetRegistry,dict(default='coding'))
        presets=ctx.agentPresets
        def definition(identity,tool,**extra):return dict(id=identity,plugins=[dict(id='tool',name='cordis:contribute',config=dict(tool=tool))],**extra)
        coding=await presets.register(definition('coding','coding_only',name='Coding',order=2))
        reviewing=await presets.register(definition('reviewing','reviewing_only',name='Review',order=1))
        rows.append(dict(roster=await presets.remoteExportList(),resolve=await presets.resolve(),inventory=await presets.compositionInventory()))
        for value in [definition('coding','duplicate'),definition(' ','blank')]:
            try:await presets.register(value)
            except Exception as error:rows.append(dict(error=str(error)))
        bad=await presets.register(dict(id='bad',plugins=[None]))
        rows.append(dict(broken=await presets.resolve('bad')))
        await bad()
        async def parent_setup(child,agent):await presets.mount(child,'coding')
        parent_handle=await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model'),setup=parent_setup))
        parent=parent_handle.agent;agents.append(parent_handle)
        def visible(agent):return dict(preset=presets.composedPreset(agent.ctx),tools=[tool['name'] for tool in ctx.tools.schemas(agent)])
        rows.append(dict(parent=visible(parent),compositions=[row['id'] for row in presets.inspectCompositions()]))
        async def child_setup(child,agent):presets.composeFrom(child,parent.ctx)
        inherited_handle=await ctx.agents.create(dict(sessionId='inherited',setup=child_setup));agents.append(inherited_handle)
        inherited=inherited_handle.agent
        rows.append(dict(inherited=visible(inherited)))
        lease=await presets.acquireScope('coding')
        await coding()
        rows.append(dict(roster=await presets.list(),parent=visible(parent),inherited=visible(inherited),revisions=[row['id'] for row in presets.inspectCompositions()]))
        coding_new=await presets.register(definition('coding','coding_v2'))
        async def new_setup(child,agent):await presets.mount(child,'coding')
        newest_handle=await ctx.agents.create(dict(sessionId='newest',setup=new_setup));agents.append(newest_handle)
        rows.append(dict(parent=visible(parent),newest=visible(newest_handle.agent),revisions=[row['id'] for row in presets.inspectCompositions()]))
        rows.append(dict(selected=await presets.select(parent,'reviewing'),stored=presets.presetForSession(parent.session),parent=visible(parent),inherited=visible(inherited)))
        before=len(parent.session.snapshotEvents());await presets.select(parent,'reviewing')
        rows.append(dict(selectionNoop=len(parent.session.snapshotEvents())==before))
        await inherited_handle.dispose();await lease.dispose();await lease.dispose()
        rows.append(dict(revisions=[row['id'] for row in presets.inspectCompositions()]))
        tool=await ctx.plugin(SubagentDelegationTool,dict(provider='spawn',allowedAgentPresets=['coding','reviewing']))
        for name,preset in [('independent','coding'),('inherited',None)]:
            args=dict(name=name,prompt='Task',description='Focused task')
            if preset is not None:args['agent_preset']=preset
            result=await ctx.tools.execute(ToolExecutionInput('call-'+name,'subagent',args,agent=parent,signal=fixture.signal))
            child=ctx.agents.get(await fixture.service.resolveName(parent,name,fixture.signal))
            rows.append(dict(delegated=result.value,child=visible(child),header=child.session.header.get('agentPreset')))
        await tool.dispose()
        from scripts.oracles.agent_machine_current_python import ScriptAdapter
        requests=[]
        class Recording(ScriptAdapter):
            async def stream(self,request):
                requests.append(request)
                async for chunk in super().stream(request):yield chunk
        chunks=[dict(type='block-start',index=0,blockType='text'),dict(type='text-delta',index=0,text='recorded'),
            dict(type='block-end',index=0,block=dict(type='text',text='recorded')),dict(type='finish',reason=dict(kind='stop'))]
        ctx.llm.registerAdapter(['record'],Recording(dict(script=[chunks,chunks])))
        for name,preset in [('model-selected','coding'),('model-inherited',None)]:
            request=dict(provider='spawn',parent=parent,name=name,label='Model task',prompt=[dict(type='text',text='Task')],
                signal=fixture.signal,delivery='caller',agentOptions=dict(provider='record',model='model'))
            if preset is not None:request['agentPreset']=preset
            receipt=await fixture.service.startActivation(request)
            result=await receipt['result'];await receipt['dispose']()
            rows.append(dict(modelResult=result,modelTools=[tool['name'] for tool in requests[-1]['tools']],
                promptContainsPresetSection='section for '+('coding_v2' if preset else 'reviewing_only') in json.dumps(requests[-1]['messages'],default=str)))
        parent.session.append('turn/start',dict(turn=1))
        try:await presets.select(parent,'coding')
        except Exception as error:rows.append(dict(locked=dict(code=error.code,message=str(error),details=error.details)))
        detached=create_scope(ctx,ScopeKey('detached'))
        try:await presets.mount(ctx,'coding')
        except Exception as error:rows.append(dict(unscoped=str(error)))
        await detached.dispose()
        await reviewing();await coding_new()
        rows.append(dict(roster=await presets.list(),remaining=[row['id'] for row in presets.inspectCompositions()]))
        ctx.loader.builtins['preset'] = CurrentAgentPreset
        from dsh.cordis.loader import EntryTree
        declarations = EntryTree(ctx)
        await declarations.root.update([dict(id='declared',name='cordis:preset',config=dict(id='declared',plugins=[
            dict(id='expression',name='cordis:contribute',config=dict(tool=dict(__jsExpr="'declared_tool'")))]))])
        rows.append(dict(declared=await presets.resolve('declared'),preservedExpression='!!js' in (await presets.readDocument('declared'))['content']))
        await declarations.root.update([])
        await declarations.wait()
        rows.append(dict(declarationRemoved='declared' not in [row['id'] for row in await presets.list()]))
        disposers=[]
        for identity in ['Z','z','á','a','A','中']:
            disposers.append(await presets.register(dict(id=identity,plugins=[])))
        rows.append(dict(sortedIds=[row['id'] for row in await presets.list()]))
        for dispose in disposers:await dispose()
        return json.loads(json.dumps(rows))
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_preset_registry.mts','Declarative eager registration, diagnostics, retained revisions and leases, exact inherited composition, replacement, blank-session selection and durable projection, no-op and locked selections, actual named delegation with independently selected versus inherited presets, provider-owned cleanup.',
        [Path(__file__).resolve(),ROOT/'dsh/presets/registry_current.py',ROOT/'dsh/cordis/loader.py'],prepare=prepare)
