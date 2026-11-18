"""Observe Loader reference commits through the public production entry."""
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def native():
    from dsh.cordis import Context, Loader, Schema as z
    result = {}
    for mode in ('ordinary', 'retained', 'throwing', 'whole'):
        ctx = Context(); loader = Loader(ctx); ctx.set_service('loader', loader)
        applied = []; disposed = []; events = []; hooks = []
        schema = z.object({'fixed': z.string().default('fixed'),
                           'title': z.string().default('hello').volatile(),
                           'count': z.number().min(0).default(1).volatile()})
        if mode == 'whole': schema = z.object({'title': z.string()}).volatile()

        def plugin(owner, config):
            applied.append(config)
            owner.effect(lambda: lambda: disposed.append(len(disposed)))
            def listener(paths):
                events.append([paths, dict(config.get()) if mode == 'whole' else
                               [config['title'].get(), config['count'].get()]])
                if mode == 'throwing': raise ValueError('listener rejected')
            owner.on('loader/volatile-update', listener)
            if mode == 'retained':
                owner.on('internal/update', lambda candidate: hooks.append(candidate['title'].get()))
        plugin.Config = schema
        loader.register_plugin_class('probe', plugin)
        first_id = await loader.create({'id': 'first', 'name': 'probe', 'config': {'title': 'hello'}})
        entry = loader.resolve(first_id); fiber = entry.fiber; await fiber
        await loader.create({'id': 'second', 'name': 'probe', 'config': {'title': 'hello'}})
        await loader.wait()
        initial = fiber.effectiveConfig; reference = initial if mode == 'whole' else initial['title']
        await entry.update({'config': {'title': 'next', **({} if mode == 'whole' else {'count': 2})}})
        result[mode + '-commit'] = [len(applied), fiber.effectiveConfig is initial,
                                   (initial if mode == 'whole' else initial['title']) is reference,
                                   list(events), list(hooks), list(disposed)]
        if mode != 'whole':
            await entry.update({'config': {'title': 'rejected', 'count': -1}})
            result[mode + '-invalid'] = [fiber.rawConfig, reference.get(), len(applied), len(events)]
            await entry.update({'config': {'fixed': 'other', 'title': 'mixed'}}); await fiber
            result[mode + '-mixed'] = [len(applied), fiber.effectiveConfig is initial,
                                      reference.get(), fiber.effectiveConfig['title'].get(),
                                      list(hooks), len(events), len(disposed)]
        await ctx.fiber.dispose()
    return result


if __name__ == '__main__':
    probe.native = native
    probe.main(observer='rc022_loader_volatile.mts',
               scope='Production Loader entry: immutable reference identity, atomic local notification, invalid raw retention, mixed updates and retained hooks.',
               extra_inputs=[ROOT / 'dsh/cordis/loader.py', ROOT / 'dsh/cordis/fiber.py',
                             ROOT / 'scripts/rc022_loader_volatile_probe.py',
                             ROOT / 'reference/vendor/loader/src/config/entry.ts'])
