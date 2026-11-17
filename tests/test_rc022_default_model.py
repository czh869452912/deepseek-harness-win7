import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis import Context,Loader
from dsh.cordis.utils import _UNDEFINED
from dsh.core.default_model_current import CurrentAgentDefaultModelConfig
from scripts.rc022_default_model_probe import observe


@pytest.mark.asyncio
async def test_live_loader_save_failure_recovery_and_optional_settings():
    rows={row['step']:row for row in await observe()}
    assert len(rows)==10
    assert rows['live']['value']==dict(provider='q',model='n',reasoningEffort='high')
    assert rows['live']['sameFiber'] is True
    assert len(rows['held']['calls'])==1
    assert rows['saved']['value']==dict(provider='test',model='final',reasoningEffort='7')
    assert rows['cleared']['value']==dict(provider='test',model='clear')
    assert rows['disposed']['calls']==[dict(policy=dict(auto=False),owner=True),'released']


@pytest.mark.asyncio
async def test_abandoned_save_keeps_order_and_undefined_effort_is_omitted():
    ctx=Context();loader=Loader(ctx);ctx.set_service('loader',loader)
    loader.register_plugin_class('model',CurrentAgentDefaultModelConfig)
    release=asyncio.Event();entered=asyncio.Event();calls=[]
    try:
        key=await loader.create(dict(name='model',config=dict(provider='p',model='m')))
        entry=loader.resolve(key);await entry.fiber
        async def edit(owner,change):
            value=change();calls.append(value)
            if len(calls)==1:entered.set();await release.wait()
            await owner.update(dict(config=value))
        ctx.provide('configEditor',SimpleNamespace(edit=edit))
        first=ctx.agentDefaultModel.saveSelection(dict(provider='p',model='first'))
        await entered.wait();first.cancel()
        last=ctx.agentDefaultModel.saveSelection(dict(provider='p',model='last',reasoningEffort=_UNDEFINED))
        await asyncio.sleep(0);assert len(calls)==1
        release.set();await last
        assert calls==[dict(provider='p',model='first'),dict(provider='p',model='last')]
        assert ctx.agentDefaultModel.currentSelection()==calls[-1]
    finally:
        release.set();await ctx.fiber.dispose()
