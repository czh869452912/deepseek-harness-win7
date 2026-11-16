"""Pair management operations with real fleet and probe HTTP connections."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe,rc022_mcp_server_probe_probe as peer
from scripts.rc022_mcp_supervision_probe import normalized


async def observe():
    from dsh.cordis.context import Context
    from dsh.core.abort import AbortController
    from dsh.mcp.manager_current import CurrentMcpManager
    from dsh.mcp.manager_entries_current import MANAGER_CONFIG
    from dsh.cordis.volatile import update_volatile
    ctx=Context();names=set();rows=[]
    def register(spec):
        name=spec['name']
        if name in names:raise RuntimeError('occupied')
        names.add(name)
        return lambda:names.discard(name)
    ctx.set_service('tools',type('Registry',(),{'register':staticmethod(register)})())
    entry=dict(transport='streamable-http',url=peer.URL+'/native/fleet/legacy',enabled=False)
    fiber=await ctx.plugin(CurrentMcpManager,dict(servers=dict(fleet=entry)));manager=ctx.get('mcpManager')
    async def wait(predicate):
        async def spin():
            while not predicate():await asyncio.sleep(.005)
        await asyncio.wait_for(spin(),5)
    def snapshot(step):rows.append(dict(step=step,views=normalized(manager.list()),names=sorted(names)))
    try:
        await wait(lambda:manager.list()[0]['status']['state']=='disabled');snapshot('disabled')
        inspected=await manager.probe('fleet');inspected.pop('durationMs');rows.append(dict(step='probe',result=inspected));snapshot('probe-independent')
        controller=AbortController();stream=manager.watch(controller.signal)
        rows.append(dict(step='watch-first',views=normalized(await stream.__anext__())))
        candidate=MANAGER_CONFIG(dict(servers=dict(fleet=dict(entry,enabled=True))))
        update_volatile(manager.config['servers'],candidate['servers']);manager.ctx.emit('loader/volatile-update',[])
        await wait(lambda:manager.list()[0]['status']['state']=='connected');snapshot('enabled')
        rows.append(dict(step='watch-updated',views=normalized(await stream.__anext__())))
        await manager.restart('fleet');await wait(lambda:manager.list()[0]['status']['state']=='connected');snapshot('restarted')
        def contribute(child):child.get('mcpManager').register('contributed',dict(transport='streamable-http',url=peer.URL+'/native/contributed/modern'))
        contributor=await ctx.plugin(contribute)
        await wait(lambda:len(manager.list())==2 and manager.list()[1]['status']['state']=='connected');snapshot('registered')
        await contributor.dispose();await wait(lambda:len(manager.list())==1);snapshot('unregistered')
        for operation in ('restart','probe'):
            try:await getattr(manager,operation)('absent')
            except Exception as error:rows.append(dict(step='unknown-'+operation,error='Error: '+str(error)))
        controller.abort()
        try:await stream.__anext__();raise AssertionError('watch did not stop')
        except StopAsyncIteration:pass
        await fiber.dispose();snapshot('disposed')
        try:await manager.restart('fleet')
        except Exception as error:rows.append(dict(step='stopped',error='Error: '+str(error)))
        return rows
    finally:await ctx.fiber.dispose()


def prepare(output):
    peer.prepare(output)
    path=output/'input.json';path.write_text(json.dumps(dict(url=peer.URL,log=str(peer.LOG))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_mcp_manager.mts','Actual original/native fleet service: disabled probe independence, coalesced watch, enabling a live volatile entry, restart, plugin-scoped registration/disposal, unknown names and final service teardown. Actual HTTP/modern wires used; timestamps/duration normalized. Direct volatile publication models the Loader commit; actual native Loader path has separate regression tests.',[Path(__file__).resolve(),ROOT/'dsh/mcp/manager_current.py'],prepare=prepare)
    finally:peer.stop_peer()
