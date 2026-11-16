import json
from pathlib import Path

import pytest
import yaml

from dsh.boot.profile_boot import run_profile
from dsh.boot.python_package_backend import PythonPackageBackend
from dsh.typert.artifact import read_generated_artifact
from test_python_plugin_distribution import profile, close, echo, PACKAGE
from test_rc022_python_package_acquire import registry_package
from test_rc022_manager_wire import http, SOURCE, rpc


@pytest.mark.asyncio
async def test_canonical_profile_loader_manager_actual_http_native_package_lifecycle(profile, registry_package, monkeypatch):
    from dsh.boot import profile_boot
    monkeypatch.setattr(profile_boot, 'INSTALL_ANCHOR', str(SOURCE/'apps/cli/package.json'))
    home, directory = profile
    path = directory/'cordis.patch.yml'; patches = yaml.safe_load(path.read_text(encoding='utf-8'))
    specs = [('plugin-manager', dict(registry=registry_package['url'], fallbackRegistries=[], lockWaitMs=0, idleTimeoutMs=10000)),
        ('typert-registry', {}), ('api-remote-access', {}), ('api-gateway', dict(websocketCompression='none')),
        ('api-remotes', {}), ('credentials-local', dict(path=str(home/'credentials.yaml'))), ('client-connection', {}),
        ('host-webserver', dict(host='127.0.0.1', port=0)), ('hmr', dict(root=[], ignored=[], debounce=0))]
    rows = [dict(id=name, name='@deepseek-ai/dsh-'+name, config=config) for name, config in specs]
    rows.append(dict(id='timer', name='@deepseek-ai/cordis-plugin-timer'))
    patches[0]['insert'].extend(rows); path.write_text(yaml.safe_dump(patches, sort_keys=False), encoding='utf-8')
    host = await run_profile(dict(profile='python-test', dshHome=str(home), args=[], waitForExit=False)); ctx = host['ctx']
    observations = []
    try:
        entry = next(entry for entry in ctx.loader.entries() if entry.options.get('id') == 'plugin-manager')
        assert entry.fiber is not None and ctx.pluginManager.owner_entry_id == entry.id
        certificate = Path(__file__).parent/'fixtures/tls/localhost-cert.pem'
        await ctx.plugin(PythonPackageBackend, dict(env=dict(registry_package['env'], PATH='', SSL_CERT_FILE=str(certificate.resolve()))))
        await ctx.hmr.runExclusive(lambda: None)
        ctx.typert.register(read_generated_artifact(SOURCE/'packages/boot/plugin-manager/lib/typert.host.js'))
        response = await http(ctx.webServer, '/connect?interactions=answer&token='+ctx.connection.browser_auth.launch_token)
        assert response['status'] == 302, response
        cookie = response['headers']['set-cookie'].split(';')[0]
        async def call(method, args):
            result = await rpc(ctx.webServer, cookie, method, args); observations.append(dict(method=method, result=result))
            assert result['ok'], result
            return result.get('value')
        installed = await call('installBundle', dict(spec=PACKAGE, options=dict(requestId='loader-install')))
        assert installed['application'] == 'applied' and installed['packageResult']['nativeCommitted']
        assert await echo(ctx) == 'Python echo: hello'
        assert any(row['name'] == PACKAGE and row['enabled'] for row in await call('listBundles', {}))
        await call('setBundleEnabled', dict(name=PACKAGE, enabled=False))
        assert ctx.tools.get('python_echo') is None
        await call('setBundleEnabled', dict(name=PACKAGE, enabled=True))
        assert await echo(ctx) == 'Python echo: hello'
        removed = await call('removeBundle', dict(name=PACKAGE))
        assert removed['application'] == 'applied'
        assert not (directory/'node_modules'/PACKAGE).exists() and ctx.tools.get('python_echo') is None
        assert not ctx.pythonProfileLease.exclusive
        (home/'manager-binding-wire-observations.json').write_text(json.dumps(observations, indent=2), encoding='utf-8')
        (home/'candidate-inputs.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    finally:
        await close(host)
