"""Exercise active Loader assembly rather than the unused split draft."""
import asyncio
from dsh.cordis import Context, Loader, Schema as z, FiberState
from scripts.rc022_loader_volatile_probe import native


def test_reference_commits_invalid_candidates_mixed_updates_and_local_events():
    observed = asyncio.run(native())
    for mode in ('ordinary', 'retained', 'throwing'):
        assert observed[mode + '-commit'] == [2, True, True,
            [[[['title'], ['count']], ['next', 2]]], [], []]
        assert observed[mode + '-invalid'] == [
            {'title': 'rejected', 'count': -1}, 'next', 2, 1]
        assert observed[mode + '-mixed'] == (
            [2, False, 'next', 'mixed', ['mixed'], 1, 0] if mode == 'retained' else
            [3, False, 'next', 'mixed', [], 1, 1])
    assert observed['whole-commit'] == [2, True, True, [[[[]], {'title': 'next'}]], [], []]


def test_pending_config_is_retained_until_dependency_activation():
    async def run():
        ctx = Context(); loader = Loader(ctx); ctx.set_service('loader', loader)
        applied = []
        def plugin(owner, config): applied.append(config)
        plugin.Config = z.object({'live': z.number().min(0).volatile()})
        plugin.inject = ['dependency']
        loader.register_plugin_class('consumer', plugin)
        key = await loader.create({'name': 'consumer', 'config': {'live': 1}})
        entry = loader.resolve(key); fiber = entry.fiber
        assert fiber.state == FiberState.PENDING
        await entry.update({'config': {'live': 2}})
        assert not applied and fiber.rawConfig == {'live': 2}
        ctx.provide('dependency', 1); await fiber
        assert len(applied) == 1 and applied[0]['live'].get() == 2
        await ctx.fiber.dispose()
    asyncio.run(run())


def test_raw_volatile_diff_with_ordinary_resolved_change_uses_update_hooks():
    async def run():
        ctx = Context(); loader = Loader(ctx); ctx.set_service('loader', loader)
        ordinary = ['initial']; configs = []; updates = []; events = []
        schema = z.object({'fixed': z.string(), 'live': z.string().volatile()})
        def plugin(owner, config):
            configs.append(config)
            owner.on('internal/update', lambda candidate: updates.append(candidate))
            owner.on('loader/volatile-update', lambda paths: events.append(paths))
        plugin.Config = schema
        loader.register_plugin_class('consumer', plugin)
        def resolve(target, next_fn):
            value = next_fn()
            if target.runtime and target.runtime.Config is schema:
                return dict(value, fixed=ordinary[0])
            return value
        ctx.on('internal/config', resolve)
        key = await loader.create({'name': 'consumer', 'config': {'fixed': 'raw', 'live': 'first'}})
        entry = loader.resolve(key); fiber = entry.fiber; await fiber
        old = fiber.effectiveConfig; ordinary[0] = 'changed'
        await entry.update({'config': {'fixed': 'raw', 'live': 'second'}})
        assert len(configs) == len(updates) == 1 and not events
        assert old['live'].get() == 'first'
        assert fiber.effectiveConfig['live'].get() == 'second'
        assert fiber.effectiveConfig['fixed'] == 'changed'
        await ctx.fiber.dispose()
    asyncio.run(run())


def test_force_volatile_commit_keeps_references_and_patches_context_once():
    async def run():
        ctx = Context(); loader = Loader(ctx); ctx.set_service('loader', loader)
        def plugin(owner, config): pass
        plugin.Config = z.string().volatile()
        loader.register_plugin_class('consumer', plugin)
        key = await loader.create({'name': 'consumer', 'config': 'first'})
        entry = loader.resolve(key); fiber = entry.fiber; await fiber
        reference = fiber.effectiveConfig; patches = []
        def patch(target, next_fn):
            patches.append(target); return next_fn()
        ctx.on('loader/patch-context', patch)
        await entry.update({'config': 'second'}, force=True)
        assert reference is fiber.effectiveConfig and reference.get() == 'second'
        assert patches == [entry]
        await ctx.fiber.dispose()
    asyncio.run(run())
