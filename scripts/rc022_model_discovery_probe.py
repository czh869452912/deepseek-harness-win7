"""Pair authorized model discovery through the actual v4 tool pipeline."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def cases():
    requests=[{},dict(provider='alpha'),dict(provider='alpha',model='hidden'),dict(provider='alpha',model='fast'),
        dict(provider='beta'),dict(provider='beta',model='plain'),dict(model='fast'),dict(provider=''),dict(provider='alpha',model=''),
        dict(provider='missing'),dict(provider='alpha',model='forbidden'),dict(provider=1)]
    return [dict(name='parent-route',requests=requests),
        dict(name='policy',routes=[dict(provider='alpha',model='fast'),dict(provider='alpha',model='hidden'),dict(provider='beta',model='plain'),dict(provider='missing',model='missing')],requests=requests),
        dict(name='unadvertised',routes=[dict(provider='alpha',model='hidden')],requests=[{},dict(provider='alpha'),dict(provider='alpha',model='hidden')]),
        dict(name='missing-parent',parent={},requests=[{}]),
        dict(name='absent-provider',parent=dict(provider='missing',model='missing'),requests=[{},dict(provider='missing')])]


async def observe(workspace):
    from scripts.rc022_subagent_fixture import setup
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from dsh.cordis.plugin import Plugin
    from dsh.core.tools import ToolExecutionInput
    from dsh.subagent.selection import POLICY
    from dsh.subagent.list_models import register_list_subagent_models
    rows=[]
    class Adapter(ScriptAdapter):
        def provider_info(self,provider):return dict(id=provider,name=provider.title())
        async def list_models(self,provider):return [await self.resolve_model(provider,model) for model in ['fast','plain']]
        async def resolve_model(self,provider,model,signal=None):
            result=dict(provider=provider,id=model,name=model.title(),description='Focused work.')
            if model!='plain':result['reasoning']=dict(efforts=[dict(id='low',name='Low'),dict(id='high',name='High',description='Quality first.')],defaultEffort='high')
            return result
    class Discovery(Plugin):
        inject=['tools','sessionProjections']
        async def apply(self,ctx):register_list_subagent_models(ctx,await ctx.sessionProjections.register(POLICY))
    for case in cases():
        fixture=await setup(workspace/case['name']);ctx=fixture.ctx;row=dict(name=case['name'],results=[])
        try:
            ctx.llm.registerAdapter(['alpha','beta'],Adapter({}))
            owner=await ctx.plugin(Discovery)
            parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=case.get('parent',dict(provider='alpha',model='hidden'))))).agent
            if 'routes' in case:parent.session.append('subagent/model-selection-policy',dict(allowedModels=case['routes']))
            row['schemas']=ctx.tools.schemas()
            for request in case['requests']:
                result=await ctx.tools.execute(ToolExecutionInput('call','list_subagent_models',request,agent=parent,signal=fixture.signal))
                row['results'].append(dict(isError=result.is_error,content=result.content,value=None if result.is_error else result.value))
            missing=await ctx.tools.execute(ToolExecutionInput('call','list_subagent_models',{},signal=fixture.signal))
            row['noCaller']=missing.content
            definition=ctx.tools.get_tool('list_subagent_models')
            try:await ctx.plugin(Discovery)
            except Exception:pass
            row['duplicatePreserved']=ctx.tools.get_tool('list_subagent_models') is definition
            await owner.dispose();row['released']=ctx.tools.get_tool('list_subagent_models') is None
        finally:await ctx.fiber.dispose()
        rows.append(row)
    return json.loads(json.dumps(rows))


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files'/'native'
    workspace=output/'workspace.json';workspace.write_text(json.dumps(str(output/'files')),encoding='utf-8')
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [workspace,path]


if __name__=='__main__':
    async def native():return await observe(WORKSPACE)
    probe.native=native
    probe.main('rc022_model_discovery.mts','Actual pipeline schemas, authorized provider/model/effort metadata, parent exact unadvertised fallback, missing routes/providers/callers, schema errors, duplicate owner rollback and unload.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/list_models.py'],prepare=prepare)
