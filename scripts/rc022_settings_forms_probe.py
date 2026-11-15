"""Actual live Config fibers and SettingsForms over an explicit controlled editor."""
import asyncio
import copy
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.schema import Schema as z
    from dsh.cordis.loader import Loader
    from dsh.settings.forms import SettingsForms
    ctx=Context();rows=[];events=[]
    def plugin(ctx,config):pass
    plugin.Config=z.object(dict(ordinary=z.string().required(),count=z.number().min(1).default(2).volatile(),token=z.string().role('secret').volatile(),list=z.array(z.object(dict(name=z.string().required(),token=z.string().role('secret')))).volatile()))
    base=dict(ordinary='fixed',count=2,token='private',list=[dict(name='one',token='secret')]);override={}
    try:
        await ctx.plugin(Loader);ctx.set_service('profileContext',dict(home=str(ROOT/'.goose/out/nonexistent-settings-legacy')))
        fiber=await ctx.plugin(plugin,base);entry=NS(id='probe',options=dict(id='probe',name='cordis:probe',config=copy.deepcopy(base)),fiber=fiber)
        class Editor:
            documentPath='patch.yml'
            def entries(self):return [entry]
            def configuration(self):return [dict(entry=entry,inherited=copy.deepcopy(base),override=copy.deepcopy(override))]
            async def edit(self,target,change):
                value=change(copy.deepcopy(entry.options['config']),copy.deepcopy(base))
                await fiber.update(value);entry.options['config']=value;override.clear();override.update(value)
        ctx.set_service('configEditor',Editor());ctx.on('settings/document-updated',lambda ns,revision:events.append(dict(ns=ns,revision=revision)))
        await ctx.plugin(SettingsForms);settings=ctx.settings
        def snapshot(name):
            descriptor=settings.describe(dict(redactSecrets=True))[0];descriptor.pop('schema');rows.append(dict(name=name,value=descriptor))
        snapshot('initial');policy=settings.configure(dict(auto=False),fiber);snapshot('policy')
        await settings.update('probe',dict(count=3),0);snapshot('updated')
        try:await settings.update('probe',dict(count=4),0)
        except Exception as error:rows.append(dict(name='conflict',code=error.code,expected=error.expected,actual=error.actual))
        await settings.mutate('probe',[dict(op='set',path=['list','0','name'],value='renamed')]);snapshot('mutated')
        await settings.mutate('probe',[dict(op='unset',path=['count'])]);snapshot('inherited')
        try:await settings.update('probe',dict(ordinary='changed'))
        except Exception as error:rows.append(dict(name='ordinary-refusal',message=str(error)))
        await settings.replace('probe',dict(count=5));snapshot('replaced')
        rows.append(dict(name='raw',value=entry.options['config']));policy();snapshot('policy-restored')
        rows.append(dict(name='events',values=events));return rows
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_settings_forms.mts','Actual SettingsForms and real Config fibers/Volatile updates; controlled ConfigEditor owns base/override snapshots and serial edits. Descriptor revisions, presentation policy, redaction, conflict, path edits, inherited reset and ordinary-field refusal; no profile persistence claim.',[Path(__file__).resolve(),ROOT/'dsh/settings/forms.py',ROOT/'dsh/settings/schema_current.py'])
