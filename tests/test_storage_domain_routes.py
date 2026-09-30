import json

import pytest

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.storage.domain_error import DomainError
from dsh.storage.domain_spec import define_domain, domain_table
from dsh.storage.error import StorageError
from dsh.storage.hub import StoragePlugin
from dsh.storage.plugins import StorageDomainPlugin, StorageJsonPlugin
from dsh.storage.storage_json import JsonStorageBackend


class NamedBackendPlugin(Plugin):
    inject = ['storage']

    def apply(self, ctx):
        name = self.config['name']
        backend = JsonStorageBackend(self.config['root'])
        unregister = ctx.get('storage').backend.register(name, backend)
        ctx.set_service('storageBackend:' + name, backend)

        async def close():
            unregister()
            await backend.close()

        ctx.effect(lambda: close)


def spec(name):
    return define_domain(name=name, version=1, tables={'items': domain_table(lambda value: value)})


@pytest.mark.asyncio
async def test_routed_providers_control_activation_unload_and_recovery_without_json(tmp_path):
    ctx = Context()
    await ctx.plugin(StoragePlugin)
    domain_fiber = ctx.plugin(StorageDomainPlugin, config={
        'backend': 'main', 'routes': {'routed': 'other', 'also_routed': 'other'},
    })
    await domain_fiber
    main = None
    other = None
    try:
        assert ctx.get('storageDomain', strict=False) is None
        main = ctx.plugin(NamedBackendPlugin, config={'name': 'main', 'root': str(tmp_path / 'main')})
        await main
        await domain_fiber
        assert ctx.get('storageDomain', strict=False) is None
        other = ctx.plugin(NamedBackendPlugin, config={'name': 'other', 'root': str(tmp_path / 'other')})
        await other
        await domain_fiber
        facility = ctx.get('storageDomain')
        assert ctx.get('storage').domain is facility
        assert 'json' not in ctx.get('storage').backend.names()
        default = await facility.open(spec('default'))
        routed = await facility.open(spec('routed'))
        await default.table('items').put('key', 'main-value')
        await routed.table('items').put('key', 'other-value')
        assert not (tmp_path / 'main' / 'routed.json').exists()
        assert not (tmp_path / 'other' / 'default.json').exists()
        assert json.loads((tmp_path / 'other' / 'routed.json').read_text(encoding='utf-8'))['tables']['items'] == {'key': 'other-value'}

        await other.dispose()
        await domain_fiber
        assert ctx.get('storageDomain', strict=False) is None
        with pytest.raises(StorageError) as error:
            ctx.get('storage').form('domain')
        assert error.value.code == 'form-not-mounted'
        with pytest.raises(DomainError) as error:
            default.table('items').get('key')
        assert error.value.code == 'closed'

        other = ctx.plugin(NamedBackendPlugin, config={'name': 'other', 'root': str(tmp_path / 'other')})
        await other
        await domain_fiber
        replacement = ctx.get('storageDomain')
        assert replacement is not facility
        assert (await replacement.open(spec('default'))).table('items').get('key') == 'main-value'
        assert (await replacement.open(spec('routed'))).table('items').get('key') == 'other-value'
        await domain_fiber.dispose()
        assert ctx.get('storageDomain', strict=False) is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unrelated_json_provider_does_not_gate_or_unload_non_json_facility(tmp_path):
    ctx = Context()
    await ctx.plugin(StoragePlugin)
    await ctx.plugin(NamedBackendPlugin, config={'name': 'main', 'root': str(tmp_path / 'main')})
    domain_fiber = ctx.plugin(StorageDomainPlugin, config={'backend': 'main'})
    await domain_fiber
    try:
        facility = ctx.get('storageDomain')
        unrelated = ctx.plugin(StorageJsonPlugin, config={'root': str(tmp_path / 'unrelated')})
        await unrelated
        await unrelated.dispose()
        await domain_fiber
        assert ctx.get('storageDomain') is facility
        domain = await facility.open(spec('independent'))
        await domain.table('items').put('key', 1)
        assert domain.table('items').get('key') == 1
    finally:
        await ctx.fiber.dispose()


@pytest.mark.parametrize('config', [{}, {'backend': 1}, {'backend': 'main', 'routes': {'sample': 1}}])
def test_domain_config_requires_explicit_string_routes(config):
    result = StorageDomainPlugin.Config.validate(config)
    assert 'issues' in result
