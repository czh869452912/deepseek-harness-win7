import asyncio
from dsh.cordis.context import Context
import tempfile
from pathlib import Path
from dsh.cordis.loader import Loader
from dsh.cordis.timer import TimerService
from dsh.cordis.hmr import ConfigWatcherService
async def scenario(number):
    if number == 67:
        ctx, log = Context(), []
        with tempfile.TemporaryDirectory(prefix='hmr-settled-') as directory:
            try:
                await ctx.plugin(Loader, {'baseUrl': Path(directory).as_uri() + '/'})
                await ctx.plugin(TimerService)
                await ctx.plugin(ConfigWatcherService, {'base': directory, 'root': ['.'], 'ignored': [], 'debounce': 10})
                hmr, key, filename = ctx.get('hmr'), object(), str(Path(directory) / 'config.json')
                count, checkpoint = 0, asyncio.Event()
                def observe():
                    task = hmr._config_refresh_state(key).running
                    log.append('running:' + str(bool(task and not task.done())).lower())
                    hmr._trigger_config_refresh(key, filename, refresh)
                    hmr._trigger_config_refresh(key, filename, refresh)
                    checkpoint.set()
                def refresh():
                    nonlocal count
                    count += 1
                    log.append('refresh:' + str(count))
                    if count == 1: asyncio.get_running_loop().call_soon(observe)
                hmr._trigger_config_refresh(key, filename, refresh)
                await checkpoint.wait()
                await asyncio.gather(*hmr._refresh_tasks)
                return {'log': log}
            finally:
                await ctx.fiber.dispose()

    ctx, log = Context(), []
    loop=asyncio.get_running_loop()
    def prefix():
        log.append('first')
        loop.call_soon(lambda: log.append('checkpoint'))
    def synchronous():
        prefix()
        if number==64:
            future=loop.create_future();future.set_result(None);return future
    async def asynchronous():
        prefix()
        if number==66: raise RuntimeError('rejected')
    ctx.on('event',synchronous if number in (63,64) else asynchronous)
    ctx.on('event',lambda: log.append('second'))
    try:
        await ctx.serial('event');log.append('returned')
    except RuntimeError: log.append('caught')
    await asyncio.sleep(0)
    await ctx.fiber.dispose()
    return {'log':log}
