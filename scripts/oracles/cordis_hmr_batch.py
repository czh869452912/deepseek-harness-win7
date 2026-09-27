import tempfile
from pathlib import Path
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.timer import TimerService
from dsh.cordis.hmr import ConfigWatcherService
async def scenario(number):
    ctx, log = Context(), []
    with tempfile.TemporaryDirectory(prefix='cordis-batch-') as directory:
        root=Path(directory)
        def source(label, value):
            return "from dsh.cordis.plugin import Plugin\nclass Probe%s(Plugin):\n    name='probe-%s'\n    def apply(self,c,config=None):\n        log=c.get('probeLog')\n        log.append('start:%s:%s')\n        return lambda: log.append('stop:%s:%s')\ndefault=Probe%s\n" % (label,label,label,value,label,value,label)
        try:
            ctx.baseUrl=root.as_uri()+'/'
            ctx.provide('probeLog',log)
            await ctx.plugin(Loader); await ctx.plugin(TimerService)
            await ctx.plugin(ConfigWatcherService,{'root':[]})
            loader=ctx.get('loader');hmr=ctx.get('hmr')
            for label in ('a','b'):
                filename=root/(label+'.py');filename.write_text(source(label,1),encoding='utf-8')
                await loader.root.update(loader.root.data+[{'id':label,'name':str(filename)}])
                hmr.register_module(str(filename),loader.store[label].fiber.ctx.fiber._plugin_cls)
            for label in ('a','b'):
                filename=root/(label+'.py');filename.write_text('invalid syntax !!!' if label=='b' else source(label,2),encoding='utf-8')
                hmr._trigger_module_reload(str(filename),hmr._modules[str(filename)])
            await hmr._module_reload_task
            for fiber in ctx.registry.list_fibers(): await fiber.await_settled()
            result={'log':log[:]}
            await ctx.fiber.dispose();result['finalLog']=log[:]
            return result
        finally: await ctx.fiber.dispose()
