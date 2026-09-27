"""Consumer observations corresponding to cordis_consumers.mts."""
import asyncio
import tempfile
from pathlib import Path

from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.hmr import ConfigWatcherService
from dsh.cordis.plugin import Plugin
from dsh.cordis.timer import TimerService


async def scenario(number):
    ctx, log = Context(), []
    finish = asyncio.Event()
    with tempfile.TemporaryDirectory(prefix='cordis-oracle-') as directory:
        try:
            await ctx.plugin(Loader, {'baseUrl': Path(directory).as_uri() + '/'})
            loader = ctx.get('loader')
            if number in (31, 32):
                entered = asyncio.Event()
                class Probe(Plugin):
                    name = 'probe'
                    def apply(self, c, config=None):
                        log.append('start:' + str(config['value']))
                        async def cleanup():
                            log.append('stop:' + str(config['value']))
                            if number == 32:
                                entered.set()
                                await finish.wait()
                                log.append('cleaned')
                        return cleanup
                loader.builtins['probe'] = Probe
                await loader.tree.root.update([{'id': 'one', 'name': 'cordis:probe', 'config': {'value': 1}}])
                entry = loader.tree.store['one']
                options = entry.options
                if number == 31:
                    await entry.update({'config': {'value': 2}})
                    observation = {'sameEntry': loader.tree.store['one'] is entry,
                                   'sameOptions': entry.options is options, 'value': entry.options['config']['value'],
                                   'owner': entry.fiber.entry is entry, 'log': log[:]}
                    await loader.tree.root.remove('one')
                    observation.update(after=log[:], removed='one' not in loader.tree.store)
                    return observation
                removing = asyncio.ensure_future(loader.tree.root.remove('one'))
                await entered.wait()
                pending = {'retained': loader.tree.store.get('one') is entry, 'detached': entry.fiber is None, 'log': log[:]}
                finish.set()
                await removing
                return {'pending': pending, 'log': log, 'removed': 'one' not in loader.tree.store}
            await ctx.plugin(TimerService)
            fiber = await ctx.plugin(ConfigWatcherService, {'base': directory, 'root': ['.'], 'ignored': [], 'debounce': 10})
            hmr = ctx.get('hmr')
            entered, second = asyncio.Event(), asyncio.Event()
            count = 0
            async def refresh():
                nonlocal count
                count += 1
                log.append('enter:' + str(count))
                if count == 1:
                    entered.set()
                    await finish.wait()
                log.append('exit:' + str(count))
            if number in (33, 34):
                class Key:
                    pass
                key, other = Key(), Key()
                filename = str(Path(directory) / 'missing.json')
                hmr._trigger_config_refresh(key, filename, refresh)
                await entered.wait()
                hmr._trigger_config_refresh(key, filename, refresh)
                hmr._trigger_config_refresh(key, filename, refresh)
                if number == 34:
                    async def other_refresh():
                        log.append('other')
                        second.set()
                    hmr._trigger_config_refresh(other, filename, other_refresh)
                    await second.wait()
                pending = log[:]
                finish.set()
                await asyncio.gather(*list(hmr._refresh_tasks))
                return {'pending': pending, 'log': log, 'count': count}
            filename = Path(directory) / 'present.json'
            filename.write_text('{}', encoding='utf-8')
            unregister = await hmr.register_config(str(filename), refresh)
            await entered.wait()
            if number == 36:
                old = asyncio.ensure_future(unregister())
                while hmr._configs:
                    await asyncio.sleep(0)
                def replacement():
                    log.append('replacement')
                    second.set()
                await hmr.register_config(str(filename), replacement)
                await second.wait()
                pending = {'registrations': len(hmr._configs), 'log': log[:]}
                finish.set()
                await old
                return {'pending': pending, 'log': log, 'registrations': len(hmr._configs)}
            done = False
            async def dispose():
                nonlocal done
                await fiber.dispose()
                done = True
            disposing = asyncio.create_task(dispose())
            while hmr._running:
                await asyncio.sleep(0)
            pending = {'done': done, 'log': log[:]}
            finish.set()
            await disposing
            return {'pending': pending, 'log': log, 'done': done, 'registrations': len(hmr._configs), 'removed': ctx.get('hmr') is None}
        finally:
            finish.set()
            await ctx.fiber.dispose()
