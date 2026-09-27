import asyncio
import tempfile
import sys
from pathlib import Path
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.timer import TimerService
from dsh.cordis.hmr import ConfigWatcherService

async def scenario(number):
    ctx, log = Context(), []
    with tempfile.TemporaryDirectory(prefix='cordis-module-') as directory:
        filename = Path(directory) / 'probe.py'
        dependency = Path(directory) / 'probe_dependency.py'
        sys.path.insert(0, directory)
        def source(value, fail=False):
            body = "raise RuntimeError('apply failed')" if fail else "return lambda: log.append('stop:%s')" % value
            return "from dsh.cordis.plugin import Plugin\nclass Probe(Plugin):\n    name = 'module-probe'\n    def apply(self,c,config=None):\n        log=c.get('probeLog')\n        log.append('start:%s')\n        %s\n" % (value, body) + '\ndefault = Probe\n'
        try:
            ctx.baseUrl = Path(directory).as_uri() + '/'
            ctx.provide('probeLog', log)
            await ctx.plugin(Loader)
            await ctx.plugin(TimerService)
            await ctx.plugin(ConfigWatcherService, {'root': [], 'debounce': 10000})
            dependency.write_text('VALUE = 1\n', encoding='utf-8')
            initial_source = source(1)
            if number >= 56:
                initial_source = "from probe_dependency import VALUE\n" + initial_source.replace("'start:1'", "'start:' + str(VALUE)").replace("'stop:1'", "'stop:' + str(VALUE)")
            filename.write_text(initial_source, encoding='utf-8')
            loader = ctx.get('loader')
            await loader.root.update([{'id':'probe','name':str(filename)}])
            old = loader.store['probe'].fiber.ctx.fiber
            filename.write_text('invalid syntax !!!' if number == 53 else source(2, number == 54), encoding='utf-8')
            count = [0]
            def on_reload(*args): count[0] += 1
            ctx.on('hmr/reload', on_reload)
            hmr = ctx.get('hmr')
            if number >= 56:
                filename.write_text(initial_source, encoding='utf-8')
                dependency.write_text('invalid syntax !!!' if number == 57 else 'VALUE = 2\n', encoding='utf-8')
            hmr.register_module(str(filename), old._plugin_cls)
            hmr._trigger_module_reload(str(dependency) if number >= 56 else str(filename), None if number >= 56 else old._plugin_cls)
            await hmr._module_reload_task
            for fiber in ctx.registry.list_fibers():
                try:
                    await fiber.await_settled()
                except Exception:
                    pass
            if number == 55:
                filename.write_text(source(3), encoding='utf-8')
                hmr._trigger_module_reload(str(filename), hmr._modules.get(str(filename), old._plugin_cls))
                await hmr._module_reload_task
                for fiber in ctx.registry.list_fibers():
                    await fiber.await_settled()
            current = loader.store['probe'].fiber
            observation = {'log':log[:], 'same':current.ctx.fiber is old, 'state':current.state, 'reloadEvents':count[0]}
            await ctx.fiber.dispose()
            observation['finalLog'] = log[:]
            return observation
        finally:
            await ctx.fiber.dispose()
            sys.path.remove(directory)
            sys.modules.pop('probe_dependency', None)
