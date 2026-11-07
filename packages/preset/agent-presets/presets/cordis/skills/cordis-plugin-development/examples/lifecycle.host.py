import asyncio


def plugin(ctx):
    state = {'notice': 0, 'serial': 0, 'parallel': 0, 'timer': 0, 'cancelled': False}
    ctx.provide('win7AuthoringLifecycle', state)

    def notice(value):
        state['notice'] += value

    async def serial(value):
        await asyncio.sleep(0)
        state['serial'] += value

    async def parallel(value):
        await asyncio.sleep(0)
        state['parallel'] += value

    async def middleware(data, next_fn):
        data['visited'] = True
        return await next_fn()

    def tick():
        state['timer'] += 1

    ctx.on('win7-authoring/notice', notice)
    ctx.on('win7-authoring/serial', serial)
    ctx.on('win7-authoring/parallel', parallel)
    ctx.on('win7-authoring/middleware', middleware)
    ctx.interval(tick, 20)

    async def work():
        try:
            await asyncio.sleep(3600)
        finally:
            state['cancelled'] = True

    task = asyncio.create_task(work())

    async def cleanup():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    ctx.effect(lambda: cleanup)
    harness.handle('snapshot', lambda args: dict(state))


plugin.inject = ['timer']
