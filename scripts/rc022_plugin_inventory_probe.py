"""Current Host inventory: exact Loader rows, metadata and optional compositions."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    return ['full','no-packages','no-base','no-presets','no-manager','preset-error','metadata-error','failed-value','failed-success','empty']


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.errors import ThrownValueError
    from dsh.host.plugin_inventory.current import CurrentPluginInventory
    rows=[]
    for name in corpus():
        ctx=Context();calls=[];error=RuntimeError('metadata unavailable');parents={}
        for kind,base in [('root','file:///C:/root/'),('nested','file:///C:/nested/')]:
            parents[kind]=NS(tree=NS(ctx=NS(**({} if name=='no-base' and kind=='root' else dict(baseUrl=base)))))
        if name!='no-base':ctx.baseUrl='file:///C:/root/'
        class Fiber:
            def __init__(self,state):self.state=state
            def __await__(self):
                async def settle():
                    calls.append('await-failed')
                    if name=='failed-success':return self
                    if name=='failed-value':raise ThrownValueError(dict(reason='raw'))
                    raise RuntimeError('startup failure')
                return settle().__await__()
        entries=[NS(id='state-'+str(state),options=dict(name='plugin-'+str(state)),fiber=Fiber(state),disabled=state==0,parent=parents['root']) for state in range(6)]
        entries += [NS(id='group',options=dict(group=True,name='group'),fiber=None,disabled=False,parent=parents['root']),NS(id='nested',options=dict(name='nested-plugin'),fiber=None,disabled=True,parent=parents['nested'])]
        if name=='empty':entries=[]
        def meta(module,base):
            calls.append(dict(meta=[module,base]))
            if name=='metadata-error':raise error
            return None if module=='plugin-1' else dict(name=dict(en=module,zh='插件 '+module),description=base)
        async def composition():
            calls.append('compositions')
            if name=='preset-error':raise error
            return [dict(id='engineering',name='Engineer',isDefault=True,rows=[dict(entryId='tool',moduleName='tool-fs',enabled='conditional',condition='!ctx.fs'),dict(entryId=None,moduleName='plugin-1',enabled=False,fiberState=2)]),dict(id='broken',isDefault=False,broken='unreadable preset',rows=[])]
        ctx.set_service('loader',NS(entries=lambda:entries))
        if name!='no-packages':ctx.set_service('pluginPackages',NS(metaOf=meta))
        if name!='no-presets':ctx.set_service('agentPresets',NS(compositionInventory=composition))
        if name!='no-manager':ctx.set_service('pluginManager',NS())
        owner=await ctx.plugin(CurrentPluginInventory)
        try:
            try:
                first=await ctx.pluginInventory.list()
                entries.append(NS(id='late',options=dict(name='late-plugin'),fiber=Fiber(2),disabled=False,parent=parents['nested']))
                second=await ctx.pluginInventory.list()
                result=dict(first=first,second=second)
            except Exception as failure:result=dict(error=getattr(failure,'message',str(failure)),original=failure is error)
            await owner.dispose()
            rows.append(dict(name=name,result=result,calls=calls,withdrawn=ctx.get('pluginInventory') is None))
        finally:await ctx.fiber.dispose()
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_plugin_inventory.mts','Actual Host plugin inventory plugin: live non-group Loader order and all Fiber phases, awaited startup diagnostics, local package metadata from each tree base URL, optional preset composition/state and persistent manager availability, failures and service unload. A second read sees later entries without a cache.',[Path(__file__).resolve(),ROOT/'dsh/host/plugin_inventory/current.py'],prepare=prepare)
