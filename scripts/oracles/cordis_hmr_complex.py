import sys
import tempfile
from pathlib import Path
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.timer import TimerService
from dsh.cordis.hmr import ConfigWatcherService

async def scenario(number):
    ctx, log = Context(), []
    with tempfile.TemporaryDirectory(prefix='cordis-complex-') as directory:
        root = Path(directory)
        sys.path.insert(0, directory)
        package = root / 'oraclepkg'
        package.mkdir()
        (package / '__init__.py').write_text('', encoding='utf-8')
        a, b = package / 'a.py', package / 'b.py'
        a.write_text('from . import b\ndef read(): return b.VALUE\n', encoding='utf-8')
        b.write_text('from . import a\nVALUE = 1\n', encoding='utf-8')
        plugin = root / 'probe.py'
        plugin.write_text("from oraclepkg.a import read\nfrom dsh.cordis.plugin import Plugin\nclass Probe(Plugin):\n    name='complex-probe'\n    def apply(self,c,config=None):\n        value=read()\n        log=c.get('probeLog')\n        log.append('start:'+str(value))\n        return lambda: log.append('stop:'+str(value))\ndefault=Probe\n", encoding='utf-8')
        try:
            ctx.baseUrl = root.as_uri() + '/'
            ctx.provide('probeLog', log)
            await ctx.plugin(Loader)
            await ctx.plugin(TimerService)
            await ctx.plugin(ConfigWatcherService, {'root':[]})
            loader = ctx.get('loader')
            await loader.root.update([{'id':'probe','name':str(plugin)}])
            old = loader.store['probe'].fiber.ctx.fiber
            hmr = ctx.get('hmr')
            hmr.register_module(str(plugin), old._plugin_cls)
            b.write_text('from . import a\nVALUE = 2\n', encoding='utf-8')
            hmr._trigger_module_reload(str(b), None)
            await hmr._module_reload_task
            for fiber in ctx.registry.list_fibers(): await fiber.await_settled()
            result = {'log':log[:], 'replaced':loader.store['probe'].fiber.ctx.fiber is not old}
            await ctx.fiber.dispose()
            result['finalLog'] = log[:]
            return result
        finally:
            await ctx.fiber.dispose()
            sys.path.remove(directory)
            for name in list(sys.modules):
                if name == 'oraclepkg' or name.startswith('oraclepkg.'):
                    sys.modules.pop(name, None)
