import json

import pytest

from dsh.boot.app_boot import boot
from dsh.boot.plugin_registry import _load, HARNESS_PLUGIN_CLASSES
from dsh.boot.plugin_registry_current import CURRENT_HARNESS_PLUGIN_CLASSES
from dsh.boot.profile_boot import create_app_ready
from dsh.boot.profile_context import read_profile_patches
from dsh.cordis.schema import Schema as z
from dsh.typert.artifact import read_generated_artifact
from test_rc022_manager_wire import http, SOURCE


@pytest.mark.asyncio
async def test_profile_settings_actual_remote_write_conflict_redaction_and_cold_boot(tmp_path):
    root = tmp_path; directory = root/'profiles/test'; bundle = directory/'node_modules/test-bundle'
    bundle.mkdir(parents=True)
    def write(path, value): path.write_text(json.dumps(value), encoding='utf-8')
    write(root/'package.json', dict(name='test-installation'))
    write(directory/'package.json', dict(name='test-profile', dsh=dict(profile=dict(bundles=['test-bundle']))))
    write(bundle/'package.json', dict(name='test-bundle', version='1.0.0', dsh=dict(bundle=dict(patch='cordis.patch.yml'))))
    specs = [('config-editor', {}), ('settings', {}), ('api-settings-controller', {}), ('typert-registry', {}),
        ('api-remote-access', {}), ('api-gateway', dict(websocketCompression='none')), ('api-remotes', {}),
        ('credentials-local', dict(path=str(root/'credentials.yaml'))), ('client-connection', {}),
        ('host-webserver', dict(host='127.0.0.1', port=0))]
    rows = [dict(id=name, name='@deepseek-ai/dsh-'+name, config=config) for name, config in specs]
    rows.append(dict(id='probe', name='cordis:probe', config=dict(ordinary='fixed', count=2, token='private')))
    write(bundle/'cordis.patch.yml', [dict(insert=rows)]); write(directory/'cordis.yml', [])
    (directory/'cordis.patch.yml').write_text('# owned profile\n[]\n', encoding='utf-8')
    profile = dict(name='test', startedBundles=['test-bundle'], dir=str(directory), patchPath=str(directory/'cordis.patch.yml'),
        installAnchor=str(root/'package.json'), cwd=str(root), home=str(root), overlays=[], telemetryDisabledEnv=None)
    def plugin(ctx, config): pass
    plugin.Config = z.object(dict(ordinary=z.string().required(), count=z.number().min(1).default(2).volatile(), token=z.string().role('secret').volatile()))
    def prepare(ctx):
        ctx.set_service('profileContext', profile); ctx.loader.builtins['probe'] = plugin
        ready = create_app_ready(); ctx.set_service('appReady', ready['service']); ready['commit']()
        for row in rows[:-1]:
            name = row['name']; ctx.loader.harness_plugins[name] = _load(name, CURRENT_HARNESS_PLUGIN_CLASSES.get(name, HARNESS_PLUGIN_CLASSES.get(name)))
        ctx.inject(['typert'], lambda child: child.effect(lambda: child.typert.register(read_generated_artifact(SOURCE/'packages/api/settings-controller/lib/typert.host.js'))))
    async def start(): return await boot('test', str(directory/'cordis.yml'), read_profile_patches('test', profile), prepare)
    observations = []; ctx = await start()
    async def rpc(method, args):
        response = await http(ctx.webServer, '/api/settings/'+method, dict(type='client-request', rpcId=method, method='settings/'+method, payload=dict(args=args)), cookie)
        assert response['status'] == 200, response
        result = json.loads(response['body'])['result']; observations.append(dict(method=method, result=result))
        return result
    async def connect():
        response = await http(ctx.webServer, '/connect?interactions=answer&token='+ctx.connection.browser_auth.launch_token)
        assert response['status'] == 302, response
        return response['headers']['set-cookie'].split(';')[0]
    try:
        cookie = await connect()
        description = (await rpc('describe', {}))['value']
        initial = next(row for row in description['namespaces'] if row['ns'] == 'probe')
        assert description['hasDocument'] and initial['autoGenerate']
        assert initial['secrets'] == [dict(path=['token'], set=True)]
        assert 'private' not in json.dumps(description)
        changed = await rpc('update', dict(ns='probe', patch=dict(count=4, token='rotated'), expectedRevision=initial['revision']))
        assert changed['value']['value']['count'] == 4 and changed['value']['autoGenerate']
        assert 'rotated' not in json.dumps(changed)
        stale = await rpc('update', dict(ns='probe', patch=dict(count=5), expectedRevision=initial['revision']))
        assert stale['error']['code'] == 'settings/conflict', stale
        rejected = await rpc('update', dict(ns='probe', patch=dict(ordinary='changed')))
        assert rejected['error']['code'] == 'settings/rejected', rejected
        invalid = await rpc('update', dict(ns='', patch={}))
        assert invalid['error']['code'] == 'gateway/bad-request', invalid
        persisted = (directory/'cordis.patch.yml').read_text(encoding='utf-8')
        assert '# owned profile' in persisted and 'rotated' in persisted
        await ctx.fiber.dispose(); ctx = await start(); cookie = await connect()
        restarted = next(row for row in (await rpc('describe', {}))['value']['namespaces'] if row['ns'] == 'probe')
        assert restarted['value']['count'] == 4 and restarted['secrets'][0]['set']
        reset = await rpc('mutate', dict(ns='probe', ops=[dict(op='unset', path=['count'])]))
        assert reset['value']['value']['count'] == 2, reset
        (root/'settings-wire-observations.json').write_text(json.dumps(observations, indent=2), encoding='utf-8')
        (root/'candidate-inputs.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_current_settings_document_cancellation_and_failure_boundaries():
    from types import SimpleNamespace as NS
    from dsh.api.settings_current import CurrentSettingsController
    from dsh.cordis.context import Context
    from dsh.core.abort import AbortController
    from dsh.typert.remote import RemoteError, remote_methods
    ctx = Context(); control = AbortController(); opened = []
    async def opener(path, signal): opened.append(path)
    async def prepare(): return 'owned.patch.yml'
    try:
        await ctx.plugin(CurrentSettingsController, dict(openTextFile=opener))
        service = ctx.settingsController
        assert [method['method'] for method in remote_methods(service)] == ['describe', 'update', 'replace', 'mutate', 'openSettingsDocument']
        with pytest.raises(RemoteError, match='mount @deepseek-ai/dsh-settings'):
            service.describe()
        ctx.set_service('settings', NS(prepareDocument=prepare))
        assert await service.openSettingsDocument(control.signal) == dict(opened=True)
        assert opened == ['owned.patch.yml']
        async def cancelled_prepare():
            control.abort(RuntimeError('caller closed'))
            return 'unused.patch.yml'
        ctx.set_service('settings', NS(prepareDocument=cancelled_prepare))
        with pytest.raises(RemoteError) as error:
            await service.openSettingsDocument(control.signal)
        assert error.value.code == 'gateway/cancelled' and len(opened) == 1
        async def failed_prepare(): raise RuntimeError('preparation failed')
        ctx.set_service('settings', NS(prepareDocument=failed_prepare))
        with pytest.raises(RemoteError) as error:
            await service.openSettingsDocument(AbortController().signal)
        assert error.value.code == 'gateway/internal' and 'preparation failed' in error.value.message
    finally:
        await ctx.fiber.dispose()
