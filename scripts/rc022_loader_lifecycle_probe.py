"""Observe raw publication, failed activation and retained disposed handles."""
import asyncio
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def native():
    from dsh.cordis import Context,Loader
    result={}
    for mode in ('noop','failed','import','name','disabled','create'):
        ctx=Context();await ctx.plugin(Loader);calls=[];partials=[]
        def example(owner,config):
            calls.append(config['value'])
            if mode=='failed':raise RuntimeError('activation failed')
        ctx.loader.builtins['example']=example
        ctx.loader.builtins['other']=lambda owner,config:calls.append('other')
        ctx.on('loader/partial-dispose',lambda entry,legacy,partial:partials.append(partial))
        original={'value':1};options=dict(id='a',name='cordis:example',config=original,disabled=None)
        errors=[]
        async def observe(awaitable,label):
            try:await awaitable
            except Exception:errors.append(label)
        if mode=='import':
            def fail(*args):raise RuntimeError('import failed')
            ctx.loader.import_plugin=fail
        try:
            await observe(ctx.loader.create(options),'create')
            await observe(ctx.loader.wait(),'wait')
            entry=ctx.loader.store['a'];fiber=entry.fiber
            if mode=='import':result[mode]=dict(errors=errors,fiber=fiber is not None);continue
            if mode=='failed':
                await observe(fiber,'fiber');result[mode]=dict(errors=errors,state=fiber.state,calls=calls);continue
            if mode=='noop':
                updated={'value':1}
                await entry.update({'config':updated,'disabled':None})
                result[mode]=dict(same_options=entry.options is options,entry_raw=entry.options['config'] is updated,
                    fiber_raw=fiber.rawConfig is original,disabled='disabled' in entry.options,calls=calls,partials=partials)
            elif mode=='name':
                await entry.update({'name':'cordis:other'})
                await entry.update({'config':{'value':2}});await ctx.loader.wait()
                result[mode]=dict(name=entry.options['name'],same_fiber=entry.fiber is fiber,calls=calls,partials=partials)
            elif mode=='disabled':
                await entry.update({'disabled':True})
                result[mode]=dict(retained=entry.fiber is fiber,disposed=not fiber.uid,partials=list(partials))
                await entry.update({'disabled':False});await ctx.loader.wait()
                result[mode].update(new_fiber=entry.fiber is not fiber,calls=calls)
            else:
                updated=dict(id='a',name='cordis:example',config={'value':1})
                await ctx.loader.root.create(updated);await ctx.loader.wait()
                result[mode]=dict(new_options=entry.options is updated,same_fiber=entry.fiber is fiber,
                    fiber_raw=fiber.rawConfig is original,calls=calls,partials=partials)
        finally:await ctx.fiber.dispose()
    for mode in ('init-gate','update-gate'):
        ctx=Context();await ctx.plugin(Loader);entered=asyncio.Event();release=asyncio.Event();calls=[]
        async def example(owner,config):
            if config['wait']:entered.set();await release.wait()
        ctx.loader.builtins['example']=example
        await ctx.loader.create(dict(id='a',name='cordis:example',config={'wait':mode=='init-gate'}))
        if mode=='update-gate':await ctx.loader.wait()
        fiber=ctx.loader.store['a'].fiber
        updating=asyncio.ensure_future(fiber.update({'wait':True})) if mode=='update-gate' else None
        await entered.wait()
        activated=asyncio.Event()
        def activate(owner):calls.append('active');activated.set()
        consumer=ctx.registry.inject({'loader':{'await':True}},activate)
        before=consumer.state;release.set()
        if updating is not None:await updating
        await ctx.loader.wait();await fiber
        if mode=='init-gate':await asyncio.wait_for(activated.wait(),2)
        await consumer
        result[mode]=dict(before=before,after=consumer.state,calls=calls)
        await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_loader_lifecycle.mts',scope=__doc__,extra_inputs=[ROOT/'dsh/cordis/loader.py',Path(__file__).resolve(),
        ROOT/'reference/vendor/loader/src/config/entry.ts',
        ROOT/'reference/vendor/loader/src/config/tree.ts'])
