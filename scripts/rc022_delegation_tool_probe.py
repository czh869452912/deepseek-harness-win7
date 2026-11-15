"""Pair complete delegation composition with actual providers/factory/pipeline."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def cases():
    def call(name='worker',**extra):return dict(op='call',args=dict(dict(name=name,prompt='Task',description='Focused task'),**extra))
    return [
        dict(name='spawn',commands=[dict(op='view'),call(),dict(op='view',caller='worker'),dict(call('nested'),caller='worker'),call(),dict(call('nobody'),caller='none'),dict(op='remove'),dict(op='view')]),
        dict(name='fork',config=dict(provider='fork'),commands=[dict(op='view'),call(),dict(op='view',caller='worker')]),
        dict(name='zero',config=dict(maxDepth=0),commands=[dict(op='view'),call()]),
        dict(name='volatile',commands=[dict(op='depth',value=0),dict(op='view'),call(),dict(op='depth',value=2),call('worker'),dict(op='view',caller='worker'),dict(call('nested'),caller='worker')]),
        dict(name='selection',config=dict(modelSelection=True,modelDiscovery=True),commands=[dict(op='view'),call(provider='script',model='model'),call('denied',provider='script',model='other'),call('effort',reasoning_effort='low'),call('empty',provider='',model='model')]),
        dict(name='configured',config=dict(agentOptions=dict(provider='script',model='other')),commands=[dict(op='view'),call()]),
        dict(name='forced',commands=[call(provider='script',model='model')]),
        dict(name='late',config=dict(provider='late'),commands=[dict(op='view'),dict(op='add'),dict(op='view'),call(),dict(op='remove'),dict(op='view')]),
        dict(name='shared-guidance',commands=[dict(op='sibling'),dict(op='view'),dict(op='unload'),dict(op='view')]),
        dict(name='bad-persona',config=dict(persona='retired'),commands=[]),
        dict(name='preset-missing',config=dict(agentPreset='missing'),commands=[]),
        dict(name='bad-capability',config=dict(provider='late'),commands=[dict(op='bad-provider'),dict(op='view')]),
    ]


async def observe(workspace):
    from types import SimpleNamespace as NS
    from dsh.cordis.volatile import WRITE
    from dsh.core.scope import scope_of
    from dsh.core.tools import ToolExecutionInput
    from dsh.subagent.delegation_tool import SubagentDelegationTool,METADATA
    from dsh.subagent.providers import SpawnInProcessPlugin,ForkInProcessPlugin
    from scripts.rc022_subagent_fixture import setup
    rows=[dict(kind='metadata',value=METADATA)]
    for case in cases():
        fixture=await setup(workspace/case['name']);ctx=fixture.ctx;signal=fixture.signal;row=dict(name=case['name'],results=[])
        provider_owner=fixture.provider;config=dict(dict(provider='spawn'),**case.get('config',{}));owner=None
        try:
            if config['provider']=='fork':provider_owner=await ctx.plugin(ForkInProcessPlugin)
            owner=await ctx.plugin(SubagentDelegationTool,config)
            parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model')))).agent
            for command in case['commands']:
                try:
                    op=command['op'];caller=command.get('caller','root');agent=parent
                    if caller=='none':agent=None
                    elif caller!='root':agent=ctx.agents.get(await fixture.service.resolveName(parent,caller,signal))
                    if op=='view':
                        assembly=await ctx.systemPrompt.assemble(dict(agent=agent,scope=scope_of(agent.ctx) if agent else None))
                        result=dict(schemas=ctx.tools.schemas(agent),sections=[dict(name=part['name'],text=part['text']) for part in assembly['sections'] if part['name'].startswith('tool:')],
                            depth=[dict(name=part['name'],text=part['text']) for part in assembly['contexts'] if part['name'].endswith(':depth')])
                    elif op=='call':
                        value=await ctx.tools.execute(ToolExecutionInput('call','subagent',command['args'],agent=agent,signal=signal))
                        result=dict(isError=value.is_error,content=value.content,value=None if value.is_error else value.value)
                    elif op=='depth':
                        getattr(fixture.service.config['maxDepth'],WRITE)(command['value']);result=dict(updated=True)
                    elif op=='remove':await provider_owner.dispose();result=dict(removed=True)
                    elif op=='add':provider_owner=await ctx.plugin(SpawnInProcessPlugin,dict(providerName='late'));result=dict(added=True)
                    elif op=='sibling':await ctx.plugin(SubagentDelegationTool,dict(provider='spawn',toolName='other'));result=dict(added=True)
                    elif op=='unload':await owner.dispose();result=dict(unloaded=True)
                    elif op=='bad-provider':
                        async def prepare(request):return {}
                        fixture.service.registerProvider(NS(name='late',capabilities={},inheritsParentContext=False,prepareContinuable=prepare))
                        result=dict(registered=True)
                    else:raise RuntimeError('unknown command')
                    row['results'].append(result)
                except Exception as error:row['results'].append(dict(error=str(error)))
        except Exception as error:row['error']=str(error)
        finally:
            await ctx.fiber.dispose()
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
    probe.main('rc022_delegation_tool.mts','Actual named spawn/fork tool, schemas/prompts, immediate activation, depth runtime/volatile limits, explicit and configured route preflight, missing caller, provider lifecycle and late validation, shared guidance and removed config.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/delegation_tool.py',ROOT/'dsh/subagent/delegation_metadata.json',ROOT/'scripts/oracles/rc022_delegation_metadata.mts'],prepare=prepare)
