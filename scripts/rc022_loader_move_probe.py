"""Real two-file Include moves against the fixed Source Loader."""
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
MODES=('leaf','group','collision','member-collision','same-tree','positions','disabled')


def row(key,value=1):return dict(id=key,name='cordis:example',config={'value':value})
def group(key,children):return dict(id=key,name='cordis:group',group=True,config=children)


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text('{}',encoding='utf-8');return [path]


async def native():
    from dsh.cordis import Context,Loader
    from dsh.cordis.include import Include
    result={}
    for mode in MODES:
        directory=OUTPUT/'files'/'native'/mode;directory.mkdir(parents=True)
        left=[group('outer',[group('inner',[row('a')])])] if mode in ('group','member-collision') else [row('a')]
        if mode=='disabled':left[0]['disabled']=True
        right=[group('g',[row('a',9)] if mode in ('collision','member-collision') else [])]
        if mode in ('same-tree','positions'):left=[row('a'),row('b'),group('g',[])]
        paths=[directory/'left.json',directory/'right.json']
        for path,data in zip(paths,(left,right)):path.write_text(json.dumps(data),encoding='utf-8')
        ctx=Context();ctx.baseUrl=directory.as_uri()+'/'
        await ctx.plugin(Loader);ctx.loader.builtins['include']=Include
        calls=[]
        def example(owner,config):calls.append(config['value'])
        ctx.loader.builtins['example']=example
        for key,path in zip(('L','R'),paths):
            await ctx.loader.create(dict(id=key,name='cordis:include',config={'path':path.as_uri()}))
            await ctx.loader.wait()
        await ctx.loader.wait()
        source=ctx.loader.store['L'].subtree;target=ctx.loader.store['R'].subtree
        name='outer' if mode in ('group','member-collision') else 'a'
        entry=source.store[name];member=source.store.get('a');old_fiber=member.fiber
        error=None
        try:
            try:
                if mode=='same-tree':
                    await source.update('a',{},'g',0)
                    await source.update('a',{},None,-1)
                elif mode=='positions':
                    await source.create(row('c'),None,-1)
                    await source.update('a',{},None,0)
                    await source.update('c',{},'g',-10)
                else:await ctx.loader.update('L:'+name,{'config':{'value':2}} if mode=='leaf' else {},'R:g',0)
            except ValueError as exc:error=str(exc)
            await source.flush();await target.flush();await ctx.loader.wait()
            owner=source if mode in ('collision','member-collision','same-tree','positions') else target
            result[mode]=dict(error=error,files=[json.loads(p.read_text(encoding='utf-8')) for p in paths],
                stores=[sorted(source.store),sorted(target.store)],same_entry=owner.store[name] is entry,
                same_member=owner.store['a'] is member,same_fiber=member.fiber is old_fiber,
                entry_id=entry.id,calls=calls,
                group_owner=entry.subgroup.tree is owner if entry.subgroup is not None else None)
            if mode=='group':
                await ctx.loader.remove('R:outer');await target.flush();await ctx.loader.wait()
                result[mode]['removed']=[sorted(target.store),json.loads(paths[1].read_text(encoding='utf-8')),
                    member.fiber is None or member.fiber.state!=2]
        finally:await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_loader_move.mts',prepare=prepare,
        scope='Actual two-file cross-tree leaf/group moves, recursive member collision preflight, explicit root moves, negative positions and disabled entries.',
        extra_inputs=[ROOT/'dsh/cordis/loader.py',ROOT/'dsh/cordis/include_persistence.py',Path(__file__).resolve(),
            ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/loader/src/config/tree.ts'])
