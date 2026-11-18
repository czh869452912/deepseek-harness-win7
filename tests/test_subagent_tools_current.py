"""Real tool consumers, explicit-session authority and usable cache checkpoints."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.subagent.canonical_tools_current import CurrentToolSubagent, apply_tool_subagent
from dsh.subagent.model_selection import ModelSelectionSettings
from dsh.subagent.model_selection_current import POLICY, read_policy
from dsh.subagent.control_tools import ToolSubagentControl, ToolListAgents
from dsh.session.projection_cache import SessionProjectionCache
from scripts.oracles.agent_machine_current_python import execute
from scripts.oracles.session_format_python import decode
from tests.test_subagent_runtime_current import mounted, closed


CASES=json.loads((Path(__file__).resolve().parents[1]/'scripts/oracles/subagent_tools_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['case'])
def test_retained_v3_tool_journey(case):
    assert execute(case,decode)==case['expected']


@pytest.mark.asyncio
async def test_continuable_tools_delegate_list_and_send_to_cold_child(tmp_path):
    ctx,parent,service=await mounted(tmp_path)
    try:
        fiber=await parent.agent.ctx.plugin(CurrentToolSubagent,dict(provider='spawn',backgroundMode='continuable'))
        await parent.agent.ctx.plugin(ToolSubagentControl)
        await parent.agent.ctx.plugin(ToolListAgents)
        tools=ctx.get('tools');execution=SimpleNamespace(agent=parent.agent,signal=AbortController().signal)
        value=await tools.get('subagent',parent.agent).execute(dict(description='worker',prompt='initial'),execution)
        sid=value['subagentId'];assert value['kind']=='continuable'
        await closed(ctx,sid);await parent.agent.whenIdle()
        listing=await tools.get('list_agents',parent.agent).execute({},execution)
        assert listing[0]['id']==sid and listing[0]['status']=='ready'
        sent=await tools.get('send_message',parent.agent).execute(dict(agent_id=sid,message='again'),execution)
        assert isinstance(sent['messageId'],str)
        await closed(ctx,sid);await parent.agent.whenIdle()
        observed=await ctx.get('sessionQuery').observeSession(sid)
        try:assert len([e for e in observed.events if e['type']=='turn/end'])==2
        finally:observed.dispose()
        await fiber.dispose()
        assert tools.get('subagent',parent.agent) is None
    finally:
        await service.continuations.drain();await parent.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_standing_install_reconciles_existing_agent_and_releases_sampled_tools(tmp_path):
    ctx,parent,service=await mounted(tmp_path)
    await ctx.plugin(ModelSelectionSettings,dict(enabled=True,allowedModels=[dict(provider='script',model='model')]))
    try:
        fiber=await parent.agent.ctx.plugin(CurrentToolSubagent,dict(provider='spawn',modelSelectionSettings=True))
        assert ctx.get('tools').get('list_subagent_models',parent.agent) is not None
        policy=read_policy(ctx.get('sessionProjections'),parent.agent.session)
        assert policy==[dict(provider='script',model='model')]
        ctx.get('subagentModelSelection').source=lambda:dict(enabled=False,allowedModels=[])
        ctx.emit('tools/change')
        assert ctx.get('tools').get('list_subagent_models',parent.agent) is not None
        await fiber.dispose()
        assert ctx.get('tools').get('list_subagent_models',parent.agent) is None
        assert read_policy(ctx.get('sessionProjections'),parent.agent.session) is None  # projection registration is unloaded
    finally:await parent.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_catalog_reads_actual_checkpoint_without_opening_cold_log(tmp_path):
    from dsh.subagent.listing import cold_row
    ctx,parent,service=await mounted(tmp_path)
    try:
        session=ctx.get('sessions').prepare('cached',meta=dict(createdAt=1000,origin='subagent',parentSession='parent'))
        session.append('subagent/descriptor',dict(version=3,mode='continuable',provider='spawn',label='cached child'))
        rows=ctx.get('sessionProjections').checkpoint(session)
        table={'cached':dict(identity=dict(createdAt=1000,isSeeded=False,inheritedEventCount=0),rows=rows)}
        cache=SessionProjectionCache(ctx,table,{})
        ctx.set_service('sessionProjectionCache',cache)
        async def unexpected(*args):raise AssertionError('cache hit must not open the log')
        row=await cold_row(ctx,SimpleNamespace(observeSession=unexpected),session.header,False,None)
        assert row==dict(kind='child',id='cached',mode='continuable',label='cached child',activity='inactive',hasChildren=False)
        # An inherited identity must never authorize this child's own catalog row.
        seeded=ctx.get('sessions').prepare('seeded',seed=session.snapshotEvents(),meta=dict(origin='subagent',parentSession='parent'))
        opened=[]
        async def missing(*args):opened.append(args);raise RuntimeError('missing log')
        row=await cold_row(ctx,SimpleNamespace(observeSession=missing),seeded.header,False,None)
        assert opened and row==dict(kind='diagnostic',id='seeded',reason='unavailable')
    finally:await parent.dispose();await ctx.fiber.dispose()
