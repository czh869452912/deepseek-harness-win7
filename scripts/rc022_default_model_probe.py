"""Current default model live Config and accepted profile-save ordering."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context,Loader
    from dsh.core.default_model_current import CurrentAgentDefaultModelConfig
    rows=[];ctx=Context();loader=Loader(ctx);ctx.set_service('loader',loader)
    loader.register_plugin_class('model',CurrentAgentDefaultModelConfig)
    try:
        key=await loader.create(dict(name='model',config=dict(provider='p',model='m')))
        entry=loader.resolve(key);fiber=entry.fiber;await fiber;service=ctx.get('agentDefaultModel')
        async def replace(value):await entry.update(dict(config=value));await entry.fiber
        rows.append(dict(step='initial',value=service.currentSelection()))
        await replace(dict(provider='q',model='n',reasoningEffort='high'))
        detached=service.currentSelection();detached['model']='mutated'
        rows.append(dict(step='live',value=service.currentSelection(),sameFiber=entry.fiber is fiber))
        await replace(dict(provider='p',model='m'));await service.saveSelection(dict(provider='ignored',model='ignored'))
        rows.append(dict(step='no-editor',value=service.currentSelection()))
        entered=asyncio.Event();release=asyncio.Event();calls=[]
        async def edit(owner,change):
            value=change();calls.append(dict(owner=owner is entry,value=value))
            if value['model']=='rejected':entered.set();await release.wait();raise RuntimeError('read-only document')
            await replace(value)
        ctx.provide('configEditor',SimpleNamespace(edit=edit))
        first=service.saveSelection(dict(provider='p',model='rejected'));next_selection=dict(provider='test',model='final',reasoningEffort=7)
        last=service.saveSelection(next_selection);next_selection['model']='mutated';await entered.wait()
        rows.append(dict(step='held',calls=list(calls)));release.set()
        try:await first
        except Exception as error:rows.append(dict(step='rejected',error=str(error)))
        await last;rows.append(dict(step='saved',calls=list(calls),value=service.currentSelection()))
        await service.saveSelection(dict(provider='test',model='clear'))
        rows.append(dict(step='cleared',value=service.currentSelection()))
        policy=[]
        def configure(value,owner):
            policy.append(dict(policy=value,owner=owner.entry is entry))
            return lambda:policy.append('released')
        ctx.provide('settings',SimpleNamespace(configure=configure));await ctx.fiber
        for _ in range(100):
            if policy:break
            await asyncio.sleep(0)
        rows.append(dict(step='settings',calls=list(policy)));await fiber.dispose()
        rows.append(dict(step='disposed',calls=list(policy)))
    finally:await ctx.fiber.dispose()
    ctx=Context()
    try:
        await ctx.plugin(CurrentAgentDefaultModelConfig,config=dict(provider='alone',model='original'))
        ctx.provide('configEditor',SimpleNamespace(edit=lambda *_:(_ for _ in ()).throw(AssertionError('no entry'))))
        await ctx.agentDefaultModel.saveSelection(dict(provider='ignored',model='ignored'))
        rows.append(dict(step='no-entry',value=ctx.agentDefaultModel.currentSelection()))
    finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_default_model.mts','Actual Loader live Config references, detached selection, missing editor/entry, held failed save followed by captured complete selection, omission clears reasoning effort, optional Settings policy and reversible cleanup.',[Path(__file__).resolve(),ROOT/'dsh/core/default_model_current.py'])
