import json
import asyncio

import pytest

from dsh.api.settings import SettingsController
from dsh.cordis.context import Context
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.settings.settings_file import SettingsFilePlugin
from dsh.typert.registry import TypertRegistry
from dsh.typert.artifact import UNDEFINED, read_generated_artifact
from dsh.typert.dispatch import RemoteDispatcher
from dsh.typert.remote import TypertRemoteFailure
from canonical_web_fixture import web_context, close_web_context


@pytest.mark.asyncio
async def test_formal_web_settings_over_authenticated_http(tmp_path):
    """Exercise serialization of every shipped namespace, not a fixture schema."""
    ctx = await web_context(tmp_path)
    try:
        async def request(method, path, body=b'', cookie=b''):
            reader, writer = await asyncio.open_connection('127.0.0.1', ctx.get('webServer').port)
            headers = ('%s %s HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n'
                       'Content-Type: application/json\r\nContent-Length: %s\r\n' %
                       (method, path, len(body))).encode('ascii')
            writer.write(headers + b'Cookie: ' + cookie + b'\r\n\r\n' + body)
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            return response

        login = await request('GET', '/?token=' + ctx.get('connection').browser_auth.launch_token)
        cookie = next(line.split(b': ', 1)[1].split(b';', 1)[0] for line in login.split(b'\r\n')
                      if line.lower().startswith(b'set-cookie:'))

        async def call(method, payload):
            body = json.dumps(dict(type='client-request', rpcId='settings-test', method='settings/' + method,
                                   payload={'args': payload})).encode('utf-8')
            response = await request('POST', '/api/settings/' + method, body, cookie)
            assert b'200 OK' in response.split(b'\r\n', 1)[0], response
            result = json.loads(response.split(b'\r\n\r\n', 1)[1])['result']
            assert result['ok'], result
            return result['value']

        directory = await call('describe', {})
        rows = {row['ns']: row for row in directory['namespaces']}
        assert {'agent-presets', 'llm-deepseek', 'llm-pi-ai', 'shell', 'subagent-model-selection'} <= rows.keys()
        from dsh.cordis.schema import Schema
        schema = Schema(rows['agent-presets']['schema'])
        assert schema({'default': 'minimal'}) == {'default': 'minimal'}
        with pytest.raises(Exception):
            schema({'default': 123})
        updated = await call('update', dict(ns='agent-presets', patch={'default': 'minimal'},
                                           expectedRevision=rows['agent-presets']['revision']))
        assert updated['value']['default'] == ctx.get('agentPresets').default_id == 'minimal'
        assert (await call('describe', {}))['namespaces']
    finally:
        await close_web_context(ctx)


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
