"""Mutation prefixes and structural teardown ownership in the real Loader."""
import asyncio
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def native():
    from dsh.cordis import Context,Loader
    result={}
    for mode in ('remove','stop','replace','import','concurrent-import'):
        ctx=Context();await ctx.plugin(Loader);loader=ctx.loader
        entered=asyncio.Event();release=asyncio.Event();cleaned=[];calls=[];partials=[];commits=[]
        async def cleanup():entered.set();await release.wait();cleaned.append(True)
        def example(owner,config):
            calls.append(config['value'])
            if mode in ('remove','stop'):owner.effect(lambda:cleanup)
        loader.builtins['example']=example
        loader.commit=lambda change:commits.append(change['options']['id'] if 'options' in change else '-'+change['id'])
        ctx.on('loader/partial-dispose',lambda entry,old,partial:partials.append([entry.options['id'],partial]))
        options=dict(id='a',name='cordis:example',config={'value':1})
        try:
            if mode in ('import','concurrent-import'):
                imported=asyncio.get_running_loop().create_future()
                def load(*args):calls.append('import');return imported
                loader.import_plugin=load
                pending=loader.create(options)
                second=loader.store['a'].init() if mode=='concurrent-import' else None
                result[mode]=dict(prefix=list(calls),pending=bool(loader.get_tasks()),registered='a' in loader.store)
                imported.set_result(example);await pending
                if second is not None:await second
                await loader.wait()
                result[mode]['calls']=calls
                continue
            await loader.create(options);await loader.wait();entry=loader.store['a'];fiber=entry.fiber
            if mode=='replace':
                newer=dict(id='a',name='cordis:example',config={'value':2})
                pending=loader.root.create(newer)
                result[mode]=dict(published=entry.options is newer,partials=list(partials))
                await pending;await loader.wait()
                empty=loader.root.update([])
                result[mode].update(empty_pending=bool(loader.get_tasks()),empty_store=list(loader.store),calls=calls)
                await empty
            else:
                pending=loader.remove('a') if mode=='remove' else loader.root.stop()
                result[mode]=dict(registered='a' in loader.store,rows=len(loader.root.data),
                    retained=entry.fiber is fiber,disposed=not fiber.uid,partials=list(partials),commits=list(commits),
                    disabled='disabled' in entry.options)
                await pending;await entered.wait();await loader.wait()
                result[mode]['cleanup_pending']=not cleaned
                shutdown=asyncio.ensure_future(ctx.fiber.dispose())
                result[mode]['shutdown_pending']=not shutdown.done()
                release.set();await shutdown;result[mode]['cleaned']=cleaned
        finally:
            release.set();await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_loader_timing.mts',scope=__doc__,extra_inputs=[ROOT/'dsh/cordis/loader.py',Path(__file__).resolve(),
        ROOT/'reference/vendor/loader/src/config/tree.ts',
        ROOT/'reference/vendor/loader/src/config/group.ts'])
