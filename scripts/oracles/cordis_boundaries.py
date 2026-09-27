import asyncio
from dsh.cordis.context import Context
async def scenario(number):
    ctx, log = Context(), []
    done = asyncio.Event()
    ready = asyncio.get_running_loop().create_future()
    ready.set_result(None)
    async def listener():
        log.append('prefix')
        if number == 59:
            await asyncio.sleep(0)
        else:
            await ready
        log.append('tail')
        done.set()
    ctx.on('event', listener)
    ctx.on('event', lambda: log.append('peer'))
    ctx.emit('event')
    immediate = log[:]
    await done.wait()
    await ctx.fiber.dispose()
    return {'immediate':immediate, 'log':log}
