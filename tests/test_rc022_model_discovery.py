import asyncio
from types import SimpleNamespace as NS
import pytest
from scripts.rc022_model_discovery_probe import observe


@pytest.mark.asyncio
async def test_pipeline_authorization_metadata_and_registration_ownership(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert all(row['released'] and row['duplicatePreserved'] for row in rows.values())
    parent=rows['parent-route']['results'];policy=rows['policy']['results']
    assert parent[0]['value']=='alpha — Alpha'
    assert parent[1]['value']=='alpha/hidden — Hidden: Focused work.'
    assert 'high (default) — High: Quality first.' in parent[2]['value']
    assert parent[3]['isError'] and 'not allowed' in parent[3]['content'][0]['text']
    assert policy[1]['value']=='alpha/fast — Fast: Focused work.'
    assert policy[5]['value'].endswith('(no advertised reasoning efforts)')
    assert 'available providers: alpha, beta' in policy[9]['content'][0]['text']
    assert rows['unadvertised']['results'][1]['value']=='(no advertised models for alpha)'
    assert 'without a parent provider and model' in rows['missing-parent']['results'][0]['content'][0]['text']
    assert rows['absent-provider']['results'][0]['value']=='(no LLM providers)'
    assert '(none)' in rows['absent-provider']['results'][1]['content'][0]['text']


@pytest.mark.asyncio
async def test_async_catalog_cancellation_preserves_exact_abort(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.core.abort import AbortController
    from dsh.subagent.selection import POLICY
    from dsh.subagent.list_models import list_subagent_models
    fixture=await setup(tmp_path);ctx=fixture.ctx
    try:
        parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model')))).agent
        policy=await ctx.sessionProjections.register(POLICY)
        parent.session.append('subagent/model-selection-policy',dict(allowedModels=[dict(provider='script',model='model')]))
        entered,release=asyncio.Event(),asyncio.Event();controller=AbortController();failure=RuntimeError('cancelled catalog')
        async def list_models(provider):
            entered.set();await release.wait();return [dict(id='model',name='Model')]
        original=ctx.llm.listModels
        ctx.llm.listModels=list_models
        try:
            pending=asyncio.create_task(list_subagent_models(ctx,policy,dict(provider='script'),NS(agent=parent,signal=controller.signal)))
            await entered.wait();controller.abort(failure);release.set()
            with pytest.raises(RuntimeError) as captured:await pending
            assert captured.value is failure
        finally:ctx.llm.listModels=original
    finally:await ctx.fiber.dispose()
