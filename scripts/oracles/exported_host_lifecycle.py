import asyncio

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.extensions.packaged_host import host_handler_service, python_host_source


NAME = '@probe/metadata-lifecycle'
SOURCE = '''counter = [0]
def plugin(ctx):
    def count(args):
        counter[0] += 1
        return counter[0]
    async def wait(args):
        await ctx.get('dependency').wait()
        return count(args)
    harness.handle('count', count)
    harness.handle('wait', wait)
    ctx.provide('mountedProbe', True)
plugin.inject = ['dependency']
'''


async def settled(ctx):
    for iteration in range(3):
        for fiber in ctx.registry.list_fibers():
            await fiber.await_settled()
        await asyncio.sleep(0)


async def rejected(callback):
    try:
        await callback
    except RuntimeError as error:
        return str(error)
    raise AssertionError('A retired handler was accepted')


async def observe_lifecycle(directory):
    rows = []
    source = directory / 'source.py'
    source.write_text(SOURCE, encoding='utf-8')
    plugin = python_host_source(str(source), NAME)
    ctx = Context()
    baseline = len(ctx.fiber.get_effects())
    try:
        provider = await ctx.plugin(lambda child: child.provide('dependency', asyncio.Event()))
        mounted = await ctx.plugin(plugin)
        original = ctx.get(host_handler_service(NAME))
        assert await original.call('count', {}) == 1
        blocked = asyncio.create_task(original.call('wait', {}))
        await asyncio.sleep(0)
        old_dependency = ctx.get('dependency')
        await provider.dispose()
        await settled(ctx)
        assert ctx.get(host_handler_service(NAME)) is None
        assert ctx.get('mountedProbe') is None
        loss_error = await rejected(original.call('count', {}))
        old_dependency.set()
        inflight_error = await rejected(blocked)
        provider = await ctx.plugin(lambda child: child.provide('dependency', asyncio.Event()))
        await settled(ctx)
        restored = ctx.get(host_handler_service(NAME))
        assert restored is original
        assert await restored.call('count', {}) == 3
        rows.append(dict(name='dependency-cycle', sameHandlers=True, restoredCounter=3,
                         lossError=loss_error, inFlightError=inflight_error))
        await provider.dispose()
        await settled(ctx)
        await mounted.dispose()
        await settled(ctx)
        assert original.closed
        assert len(ctx.fiber.get_effects()) == baseline
        provider = await ctx.plugin(lambda child: child.provide('dependency', asyncio.Event()))
        await settled(ctx)
        assert ctx.get(host_handler_service(NAME)) is None
        rows.append(dict(name='dispose-while-pending', closed=True, republished=False,
                         staleError=await rejected(original.call('count', {}))))
        await provider.dispose()
    finally:
        await ctx.fiber.dispose()

    for mount_index in range(2):
        ctx = Context()
        try:
            await ctx.plugin(lambda child: child.provide('dependency', asyncio.Event()))
            await ctx.plugin(plugin)
            handlers = ctx.get(host_handler_service(NAME))
            values = [await handlers.call('count', {}), await handlers.call('count', {})]
            assert values == [1, 2]
            rows.append(dict(name='independent-mount-' + str(mount_index), values=values))
        finally:
            await ctx.fiber.dispose()

    ctx = Context()
    try:
        mounted = await ctx.plugin(plugin)
        assert mounted.state == FiberState.PENDING
        assert ctx.get(host_handler_service(NAME)) is None
        await mounted.dispose()
        await ctx.plugin(lambda child: child.provide('dependency', asyncio.Event()))
        await settled(ctx)
        assert ctx.get('mountedProbe') is None
        rows.append(dict(name='initial-pending-disposal', bodyRan=False))
    finally:
        await ctx.fiber.dispose()

    ctx = Context()
    try:
        mounted = await ctx.plugin(plugin)
        assert mounted.state == FiberState.PENDING
        await ctx.plugin(lambda child: child.provide('dependency', asyncio.Event()))
        await settled(ctx)
        assert mounted.state == FiberState.ACTIVE
        assert await ctx.get(host_handler_service(NAME)).call('count', {}) == 1
        rows.append(dict(name='late-provider', active=True, counter=1))
    finally:
        await ctx.fiber.dispose()

    changed = directory / 'changed.py'
    changed.write_text(SOURCE, encoding='utf-8')
    changed_plugin = python_host_source(str(changed), NAME)
    changed.write_text(SOURCE.replace("['dependency']", "['other']"), encoding='utf-8')
    ctx = Context()
    try:
        await ctx.plugin(lambda child: child.provide('dependency', asyncio.Event()))
        mounted = ctx.plugin(changed_plugin)
        try:
            await mounted
        except ValueError as error:
            assert 'declaration changed' in str(error)
            rows.append(dict(name='modified-declaration', error=str(error), published=False))
        else:
            raise AssertionError('Changed metadata was accepted')
        assert ctx.get(host_handler_service(NAME)) is None
        assert ctx.get('mountedProbe') is None
    finally:
        await ctx.fiber.dispose()

    dynamic = directory / 'dynamic.py'
    dynamic.write_text(SOURCE.replace("plugin.inject = ['dependency']", "plugin.inject = list(('dependency',))"), encoding='utf-8')
    dynamic_plugin = python_host_source(str(dynamic), NAME)
    assert getattr(dynamic_plugin, 'inject', None) is None
    ctx = Context()
    try:
        mounted = ctx.plugin(dynamic_plugin)
        try:
            await mounted
        except ValueError as error:
            assert 'requires services: dependency' in str(error)
            rows.append(dict(name='dynamic-declaration-fallback', error=str(error), published=False))
        else:
            raise AssertionError('Unproven dynamic declaration was silently accepted')
        assert ctx.get('mountedProbe') is None
    finally:
        await ctx.fiber.dispose()

    return rows
