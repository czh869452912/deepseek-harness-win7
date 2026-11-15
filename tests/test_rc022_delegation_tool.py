import asyncio
import pytest
from scripts.rc022_delegation_tool_probe import observe


@pytest.mark.asyncio
async def test_actual_named_delegation_depth_routes_and_provider_lifecycle(tmp_path):
    rows={row['name']:row for row in (await observe(tmp_path))[1:]}
    spawn=rows['spawn']['results']
    assert spawn[1]['value']==dict(kind='activation',name='worker')
    assert spawn[3]['isError'] and 'maxDepth' in spawn[3]['content'][0]['text']
    assert spawn[4]['isError'] and 'already' in spawn[4]['content'][0]['text']
    assert 'calling agent' in spawn[5]['content'][0]['text']
    assert spawn[-1]['schemas']==[]
    assert rows['fork']['results'][1]['value']==dict(kind='activation',name='worker')
    assert rows['zero']['results'][-1]['isError']
    volatile=rows['volatile']['results']
    assert volatile[2]['isError'] and volatile[-1]['value']['name']=='worker/nested'
    assert rows['configured']['results'][-1]['value']['name']=='worker'
    selection=rows['selection']['results']
    assert selection[1]['value']['name']=='worker' and all(result['isError'] for result in selection[2:])
    assert rows['late']['results'][0]['schemas']==[] and rows['late']['results'][-1]['schemas']==[]
    shared=rows['shared-guidance']['results']
    assert len([part for part in shared[1]['sections'] if part['text']])==1
    assert '`other` or `subagent`' in shared[1]['sections'][0]['text']
    assert [tool['name'] for tool in shared[-1]['schemas']]==['other']
    assert 'persona is no longer supported' in rows['bad-persona']['error']
    assert 'requires the agent-presets service' in rows['preset-missing']['error']
    assert 'cannot enforce maxDepth' in rows['bad-capability']['results'][0]['error']
    from dsh.subagent.delegation_tool import DELEGATION_TOOLS
    assert DELEGATION_TOOLS==[]


@pytest.mark.asyncio
async def test_provider_replacement_during_preflight_rejects_before_child_creation(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.subagent.delegation_tool import SubagentDelegationTool,DELEGATION_TOOLS
    from dsh.subagent.providers import SpawnInProcessPlugin
    from dsh.core.tools import ToolExecutionInput
    fixture=await setup(tmp_path);ctx=fixture.ctx
    try:
        await ctx.plugin(SubagentDelegationTool,dict(provider='spawn',agentOptions=dict(provider='script',model='model')))
        parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model')))).agent
        entered,release=asyncio.Event(),asyncio.Event();original=ctx.llm.resolveCallConfig
        async def gated(options,signal):entered.set();await release.wait();return await original(options,signal)
        ctx.llm.resolveCallConfig=gated
        pending=asyncio.create_task(ctx.tools.execute(ToolExecutionInput('call','subagent',dict(prompt='Task',description='Focused task',name='worker'),agent=parent,signal=fixture.signal)))
        await entered.wait();old=ctx.tools.get_tool('subagent')
        await fixture.provider.dispose()
        await ctx.plugin(SpawnInProcessPlugin)
        assert ctx.tools.get_tool('subagent') is not old
        release.set();result=await pending
        assert result.is_error and 'changed while resolving' in result.content[0]['text']
        assert [agent.id for agent in ctx.agents.list()]==['parent']
        assert not any(event['type']=='subagent/catalog' for event in parent.session.snapshotEvents())
        ctx.llm.resolveCallConfig=original
    finally:await ctx.fiber.dispose()
    assert DELEGATION_TOOLS==[]


@pytest.mark.asyncio
async def test_scope_override_controls_guidance_and_depth(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.subagent.delegation_tool import SubagentDelegationTool
    from dsh.core.scope import scope_of
    fixture=await setup(tmp_path);ctx=fixture.ctx
    try:
        await ctx.plugin(SubagentDelegationTool,dict(provider='spawn',maxDepth=2))
        root=(await ctx.agents.create(dict(sessionId='parent'))).agent
        async def setup_agent(agent_ctx,agent):await agent_ctx.plugin(SubagentDelegationTool,dict(provider='spawn',maxDepth=0))
        scoped=(await ctx.agents.create(dict(sessionId='scoped',setup=setup_agent))).agent
        async def depth(agent):
            assembly=await ctx.systemPrompt.assemble(dict(agent=agent,scope=scope_of(agent.ctx)))
            return [part['text'] for part in assembly['contexts'] if part['name'].endswith(':depth') and part['text']]
        assert await depth(root)==[]
        assert await depth(scoped)==['Delegation depth for `subagent`: current 0, maximum 0, remaining levels 0. Do not call `subagent` at this depth; carry out the work directly.']
        inherited=(await ctx.agents.create(dict(sessionId='inherited',meta=dict(delegationDepth=2)))).agent
        assert len(await depth(inherited))==1
        restore=inherited.ctx.get('tools').restrict(dict(deny=['subagent']))
        assert await depth(inherited)==[]
        restore()
        assert len(await depth(inherited))==1
    finally:await ctx.fiber.dispose()
