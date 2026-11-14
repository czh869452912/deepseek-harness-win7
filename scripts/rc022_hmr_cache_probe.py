"""Pair real evaluated module eviction, failed imports and cache restoration."""
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text('{}', encoding='utf-8')
    return [path]


async def observe(directory):
    from dsh.cordis import Context
    from dsh.cordis.loader import Loader
    from dsh.cordis.hmr_modules import PythonModules, module_url
    directory.mkdir(parents=True)
    result = []
    for mode in ('success', 'failure', 'unrelated'):
        path = directory/(mode+'.py')
        path.write_text('value = 1\n', encoding='utf-8')
        ctx = Context()
        await ctx.plugin(Loader)
        cache = PythonModules(ctx)
        try:
            first = ctx.loader.import_plugin(str(path))
            path.write_text('value = (\n' if mode == 'failure' else 'value = 2\n', encoding='utf-8')
            retained = ctx.loader.import_plugin(str(path))
            rollback = cache.evict([path.as_uri()] if mode != 'unrelated' else ['node:fs', (directory/'absent.py').as_uri()])
            failed = False
            try:
                fresh = ctx.loader.import_plugin(str(path))
                value = fresh.value
                replaced = fresh is not first
            except SyntaxError:
                failed, value, replaced = True, None, None
            rollback()
            restored = ctx.loader.import_plugin(str(path))
            result.append(dict(case=mode, retained=retained is first, retained_value=retained.value,
                               failed=failed, value=value, replaced=replaced, restored=restored is first, restored_value=restored.value))
        finally:
            for name, module in list(sys.modules.items()):
                if module_url(module) == path.as_uri():
                    sys.modules.pop(name, None)
            await ctx.fiber.dispose()
    return result


async def native():
    return await observe(OUTPUT/'files/native')


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'.goose/out/rc022-prep-20261114-01/source'
    probe.main('rc022_hmr_cache.mts', 'Actual evaluated ESM/Python imports keep identity before eviction, evaluate changed source after eviction, and restore previous namespaces/cache after success or syntax failure. Python parent/alias/bytecode behavior has additional native checks.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr_modules.py', ROOT/'dsh/cordis/loader.py', source/'packages/boot/hmr/src/index.ts'],
               prepare, node_args=('--expose-internals',))
