"""Actual Loader/Include file reconciliation journeys against fixed Source."""
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None


def row(entry_id,value): return dict(id=entry_id,name='cordis:example',config={'value':value})


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text('{}',encoding='utf-8');return [path]


async def native():
    from dsh.cordis import Context,Loader
    from dsh.cordis.include import Include
    result={}
    for mode in ('refresh-first','update-first','conflict','recovery','patch','failed-refresh','duplicate'):
        directory=OUTPUT/'files'/'native'/mode;directory.mkdir(parents=True)
        path=directory/'root.json'
        def write(data):path.write_text(json.dumps(data),encoding='utf-8')
        write([row('a',1),row('a',2)] if mode=='duplicate' else [row('a',1),row('b',1)])
        ctx=Context();ctx.baseUrl=directory.as_uri()+'/'
        await ctx.plugin(Loader);ctx.loader.builtins['include']=Include
        entered=asyncio.Event();release=asyncio.Event()
        async def example(owner,config):
            if mode=='failed-refresh' and config['value']==2:
                entered.set();await release.wait();raise RuntimeError('rejected candidate')
        ctx.loader.builtins['example']=example
        key=await ctx.loader.create(dict(name='cordis:include',config={'path':path.as_uri()}))
        await ctx.loader.wait();include=ctx.loader.resolve(key).subtree
        errors=[]
        async def flush_error():
            try:await include.flush()
            except Exception as error:errors.append(['Error' if type(error) is RuntimeError else type(error).__name__,getattr(error,'stage',None)])
        try:
            if mode=='duplicate':
                result[mode]=[len(include.root.data),list(include.store),include.store['a'].fiber.effectiveConfig]
                continue
            if mode in ('refresh-first','update-first'):
                write([row('a',1),row('b',3)])
                calls=[include.refresh(),include.update('a',{'config':{'value':2}})]
                if mode=='update-first':calls.reverse()
                await asyncio.gather(*calls);await include.flush()
            elif mode=='conflict':
                write([row('a',3),row('b',1)])
                await include.update('a',{'config':{'value':2}});await include.flush()
            elif mode=='recovery':
                path.unlink();await include.update('a',{'config':{'value':2}});await flush_error()
                path.write_text('{',encoding='utf-8')
                try:await include.refresh()
                except Exception as error:errors.append([type(error).__name__,getattr(error,'stage',None)])
                assert path.read_text(encoding='utf-8')=='{'
                write([row('a',1),row('b',4)]);await include.refresh();await include.flush()
            elif mode=='failed-refresh':
                write([row('a',2),row('b',1)]);first=asyncio.create_task(include.refresh());await entered.wait()
                write([row('a',3),row('b',1)]);second=asyncio.create_task(include.refresh());await asyncio.sleep(0)
                if include._draining is not None:await include._draining
                release.set();await asyncio.gather(first,second);await include.flush()
            else:
                inner=directory/'inner.json';original=json.dumps([row('x',1)]);inner.write_text(original,encoding='utf-8')
                child_key=await include.create(dict(id='child',name='cordis:include',config={
                    'path':inner.as_uri(),'patches':[{'id':'x','disabled':True},{'insert':[row('y',1)]}]}))
                await ctx.loader.wait();child=include.store['child'].subtree
                await child.update('x',{'disabled':False});await child.update('y',{'config':{'value':2}})
                await child.flush();await include.flush()
                result[mode]=[inner.read_text(encoding='utf-8')==original,json.loads(path.read_text(encoding='utf-8'))[-1]['config']['patches']]
                continue
            result[mode]=[[include.store[k].fiber.effectiveConfig for k in ('a','b')],
                           json.loads(path.read_text(encoding='utf-8')),errors,len(include.journal)]
        finally:await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_include_queue.mts',prepare=prepare,
        scope='Actual production Include journal draining: independent edits in both orders, file-wins conflicts, missing/invalid file recovery and nested patch owner persistence.',
        extra_inputs=[ROOT/'dsh/cordis/include.py',ROOT/'dsh/cordis/include_persistence.py',ROOT/'dsh/cordis/loader.py',ROOT/'scripts/rc022_include_queue_probe.py',ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/include/src/index.ts'])
