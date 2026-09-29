import json

import pytest

from dsh.api.settings import SettingsController
from dsh.cordis.context import Context
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.settings.settings_file import SettingsFilePlugin
from dsh.typert.registry import TypertRegistry
from dsh.typert.artifact import UNDEFINED, read_generated_artifact
from dsh.typert.dispatch import RemoteDispatcher
from dsh.typert.remote import TypertRemoteFailure


@pytest.mark.asyncio
async def test_generated_settings_credentials_contract_persists_and_redacts(tmp_path):
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    await ctx.plugin(SettingsFilePlugin, config={'path': str(tmp_path / 'settings.yaml'), 'watch': False})
    await ctx.plugin(CredentialsLocalPlugin, config={'path': str(tmp_path / 'credentials.yaml'), 'watch': False})
    await ctx.plugin(SettingsController, config={'nativeOpen': False})
    ctx.get('typert').register(read_generated_artifact('packages/api/settings-controller/lib/typert.host.js'))
    gateway = RemoteDispatcher(ctx)
    async def call(namespace, method, **args):
        return await gateway.invoke(dict(namespace=namespace, method=method, args=args))
    settings = ctx.get('settings')
    settings.register('fixture', schema=lambda value: dict(value or {}))
    try:
        first = await call('settings', 'describe')
        assert first['writable'] and first['hasDocument']
        revision = first['namespaces'][0]['revision']
        value = await call('settings', 'update', ns='fixture', patch={'theme': 'dark'}, expectedRevision=revision)
        assert value['value']['theme'] == 'dark'
        with pytest.raises(TypertRemoteFailure) as error:
            await call('settings', 'replace', ns='fixture', section={}, expectedRevision=revision)
        assert error.value.failure['code'] == 'settings-conflict'
        assert await call('credentials', 'set', ref='FIXTURE_KEY', value='test-secret') is UNDEFINED
        info = await call('credentials', 'describe', refs=['FIXTURE_KEY'])
        assert info == {'FIXTURE_KEY': {'configured': True, 'source': 'file', 'writable': True}}
        assert 'test-secret' not in json.dumps(info)
        assert await call('credentials', 'unset', ref='FIXTURE_KEY') is UNDEFINED
        assert not (await call('credentials', 'describe', refs=['FIXTURE_KEY']))['FIXTURE_KEY']['configured']
        with pytest.raises(TypertRemoteFailure) as error:
            await call('credentials', 'describe', refs=['invalid-ref'])
        assert error.value.failure['code'] == 'bad-request'
        assert not await call('settings', 'canOpenAgentPresetDirectory')
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_settings_absent_provider_and_credential_extra_fields_are_safe():
    ctx = Context()
    await ctx.plugin(SettingsController)
    try:
        with pytest.raises(TypertRemoteFailure, match='settings service is absent'):
            ctx.get('settingsController').describe()
        class Credentials:
            def describe(self, ref):
                return dict(configured=True, writable=False, value='must-not-leak', source='env')
        ctx.set_service('credentials', Credentials())
        assert await ctx.get('credentialsController').describe(['TEST']) == {'TEST': dict(configured=True, writable=False, source='env')}
    finally:
        await ctx.fiber.dispose()
