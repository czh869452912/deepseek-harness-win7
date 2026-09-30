"""Real Python observations paired with storage-cache.spec.ts."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsh.cordis.context import Context
from dsh.core.session import SessionPlugin
from dsh.session.projections import SessionProjectionsPlugin
from dsh.session.projection_cache import SessionProjectionCachePlugin
from dsh.storage.domain_spec import define_domain, domain_table
from dsh.storage.hub import StoragePlugin
from dsh.storage.plugins import StorageDomainPlugin, StorageJsonPlugin
from dsh.storage.storage_json import JsonStorageBackend


def spec(name):
    return define_domain(name=name, version=1, tables={'items': domain_table(lambda value: value)})


def append(session, value):
    session.append('cache-test/event', {'value': value}, ignorable=True)


async def named_backend(ctx, name, root):
    def provider(inner):
        backend = JsonStorageBackend(str(root))
        unregister = inner.get('storage').backend.register(name, backend)
        inner.provide('storageBackend:' + name, backend)

        async def close():
            unregister()
            await backend.close()

        inner.effect(lambda: close)

    provider.inject = ['storage']
    return await ctx.plugin(provider)


async def cache_context(root, count=100):
    ctx = Context()
    await ctx.plugin(StoragePlugin)
    await ctx.plugin(StorageJsonPlugin, config={'root': str(root)})
    await ctx.plugin(StorageDomainPlugin, config={'backend': 'json'})
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(SessionProjectionsPlugin)
    ctx.get('sessionProjections').register({
        'key': 'count', 'stateVersion': 1, 'stateSchema': lambda value: int(value),
        'init': lambda header: 0, 'apply': lambda state, event: state + 1,
        'wire': {'viewSchema': lambda value: int(value), 'view': lambda state: state},
    })
    await ctx.plugin(SessionProjectionCachePlugin, config={'writeEveryEvents': count, 'writeIntervalMs': 60000})
    return ctx


async def settle(cache):
    while cache.tasks:
        await asyncio.gather(*list(cache.tasks))


async def run():
    rows, contexts = [], []
    with tempfile.TemporaryDirectory(prefix='dsh-storage-cache-oracle-') as directory:
        root = Path(directory)
        try:
            routed = Context()
            contexts.append(routed)
            await routed.plugin(StoragePlugin)
            fiber = routed.plugin(StorageDomainPlugin, config={'backend': 'main', 'routes': {'routed': 'other'}})
            await fiber
            gates = [routed.get('storageDomain', strict=False) is not None]
            await named_backend(routed, 'main', root / 'main')
            await fiber
            gates.append(routed.get('storageDomain', strict=False) is not None)
            other = await named_backend(routed, 'other', root / 'other')
            await fiber
            gates.append(routed.get('storageDomain', strict=False) is not None)
            old = routed.get('storageDomain')
            normal = await old.open(spec('normal'))
            remote = await old.open(spec('routed'))
            await normal.table('items').put('key', 'main')
            await remote.table('items').put('key', 'other')
            persisted = [json.loads(path.read_text(encoding='utf-8'))['tables']['items']['key'] for path in
                         [root / 'main' / 'normal.json', root / 'other' / 'routed.json']]
            await other.dispose()
            await fiber
            assert routed.get('storageDomain', strict=False) is None
            await named_backend(routed, 'other', root / 'other')
            await fiber
            fresh = routed.get('storageDomain')
            rows.append({'mode': 'routing', 'gates': gates, 'withdrawn': old is not fresh, 'persisted': persisted,
                         'recovered': [(await fresh.open(spec('normal'))).table('items').get('key'),
                                       (await fresh.open(spec('routed'))).table('items').get('key')]})

            cut = await cache_context(root / 'cut')
            contexts.append(cut)
            cache = cut.get('sessionProjectionCache')
            session = cut.get('sessions').create('cut')
            append(session, 1)
            await settle(cache)
            creation = cache.cached_snapshot(session.header)
            pending = cache.write(session)
            append(session, 2)
            await pending
            rows.append({'mode': 'call-cut', 'creation': creation, 'written': cache.cached_snapshot(session.header)})

            threshold = await cache_context(root / 'threshold', 3)
            contexts.append(threshold)
            cache = threshold.get('sessionProjectionCache')
            counted = threshold.get('sessions').create('threshold')
            await settle(cache)
            changes = []

            def changed(change):
                if change.domain == 'session_projcache' and change.key == counted.id and change.operation == 'put':
                    changes.append(change.value['rows']['count'])

            threshold.on('domain/changed', changed)
            for value in range(6):
                append(counted, value)
            await settle(cache)
            rows.append({'mode': 'threshold', 'writes': changes})

            invalid = await cache_context(root / 'invalid')
            contexts.append(invalid)
            cache = invalid.get('sessionProjectionCache')
            bad = invalid.get('sessions').create('invalid')
            await settle(cache)
            unregister = invalid.get('sessionProjections').register({
                'key': 'invalid', 'stateVersion': 1, 'stateSchema': lambda value: value,
                'init': lambda header: {'not-json'}, 'apply': lambda state, event: state,
            })
            rejected = False
            try:
                await cache.write(bad)
            except ValueError:
                rejected = True
            document = json.loads((root / 'invalid' / 'session_projcache' / 'sessions' / 'invalid.json').read_text(encoding='utf-8'))
            unregister()
            append(bad, 1)
            await cache.write(bad)
            rows.append({'mode': 'non-json', 'rejected': rejected, 'invalidPersisted': 'invalid' in document['record']['rows'],
                         'recovered': cache.cached_snapshot(bad.header)})
            Path(sys.argv[1]).write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')
        finally:
            for ctx in reversed(contexts):
                await ctx.fiber.dispose()


asyncio.run(run())
