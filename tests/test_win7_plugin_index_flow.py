"""Win7 index, registry and package service through the normal Web profile."""
import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import ssl
import threading
from urllib.parse import urlsplit
import zipfile

import pytest

from dsh.boot.profile import init_profile, PROFILE_TEMPLATES
from dsh.boot.profile_boot import run_profile
from scripts.build_plugin_index import build_index
from test_python_plugin_distribution import EXAMPLE, PACKAGE, close, echo

MARKET = '@deepseek-ai/dsh-experimental-plugin-market-bundle'


@pytest.mark.asyncio
async def test_win7_index_install_and_reopen_from_local_https(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    directory = home / 'profiles' / 'web'
    init_profile(str(directory), PROFILE_TEMPLATES['web']['bundles'])
    certificate = Path(__file__).parent / 'fixtures/tls/localhost-cert.pem'
    monkeypatch.setenv('DSH_HOME', str(home))
    monkeypatch.setenv('DSH_TELEMETRY_MODE', 'DISABLED')
    monkeypatch.setenv('SSL_CERT_FILE', str(certificate.resolve()))
    monkeypatch.setenv('NO_PROXY', 'localhost,127.0.0.1')
    npmrc = tmp_path / 'npmrc'
    npmrc.write_text('', encoding='utf-8')
    monkeypatch.setenv('NPM_CONFIG_USERCONFIG', str(npmrc))
    site = tmp_path / 'site'
    requests = []

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(urlsplit(self.path).path)
            super().do_GET()

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(site))) as server:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(str(certificate), str(certificate.with_name('localhost-key.pem')))
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        base = 'https://localhost:' + str(server.server_port) + '/'
        index = base + 'index.json'
        other = base + 'other.json'
        registry = base + 'registry/'
        local_zip = tmp_path / 'plugin.zip'
        with zipfile.ZipFile(local_zip, 'w') as archive:
            for file in EXAMPLE.rglob('*'):
                if file.is_file() and '__pycache__' not in file.parts:
                    archive.write(file, 'wrapped/' + file.relative_to(EXAMPLE).as_posix())
        build_index(site, base, [EXAMPLE], 1700000000, 'Win7 fixture')
        (site / 'other.json').write_bytes((site / 'index.json').read_bytes())
        (directory / 'cordis.patch.yml').write_text(
            '- id: plugin-market\n  config:\n    indexes: [' + index + ', ' + other + ']\n'
            '    compatibleIndexes: [' + index + ']\n'
            '- id: plugin-manager\n  config:\n    registry: ' + registry + '\n    fallbackRegistries: []\n',
            encoding='utf-8')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        async def boot():
            return await run_profile(dict(profile='web', dshHome=str(home), waitForExit=False,
                args=['--host', '127.0.0.1', '--port', '0', '--no-open']))

        try:
            host = await boot()
            try:
                ctx = host['ctx']
                assert ctx.get('profilePackages') is not None
                toggle = await ctx.pluginManager.setBundleEnabled(MARKET, True)
                assert toggle['application'] == 'applied', toggle
                assert any(row['id'] == '@deepseek-ai/dsh-client-ui-plugin-market'
                           for row in ctx.clientModules.graph()['entries'])
                query = dict(offset=0, limit=10, sort=dict(kind='index'))
                row, = (await ctx.pluginMarket.search(index, query))['entries']
                other_row, = (await ctx.pluginMarket.search(other, query))['entries']
                assert row['defaultVersion'] == '0.1.0'
                assert 'defaultVersion' not in other_row
                assert other_row['versions'][0]['compatibility']['exempted'] is False
                assert (await ctx.pluginManager.inspect(str(local_zip)))['name'] == PACKAGE
                target = row['versions'][0]['install']
                missing = await ctx.pluginManager.installBundle('@example/missing@1.0.0',
                    dict(registry=registry, enabled=False))
                assert missing['application'] == 'failed' and missing['registries'] == [registry]
                result = await ctx.pluginManager.installBundle(target['spec'], dict(registry=target['registry']))
                assert result['application'] == 'applied' and result['packageResult']['nativeCommitted'], result
                assert await echo(ctx) == 'Python echo: hello'
            finally:
                await close(host)

            host = await boot()
            try:
                ctx = host['ctx']
                assert await echo(ctx) == 'Python echo: hello'
                installed, = (await ctx.pluginMarket.search(index, query))['entries']
                assert installed['installation']['status'] == 'installed'
                removed = await ctx.pluginManager.removeBundle(PACKAGE)
                assert removed['application'] == 'applied', removed
                assert ctx.tools.get('python_echo') is None
                broken = tmp_path / 'broken'
                shutil.copytree(EXAMPLE, broken, ignore=shutil.ignore_patterns('__pycache__'))
                (broken / 'python/echo/plugin.py').write_text(
                    "raise RuntimeError('Win7 activation fixture')\n", encoding='utf-8')
                rejected = await ctx.pluginManager.installBundle(str(broken))
                assert rejected['application'] == 'failed', rejected
                retry = await ctx.pluginManager.setBundleEnabled(PACKAGE, True)
                assert retry['application'] == 'failed', retry
                row = next(row for row in await ctx.pluginManager.listBundles() if row['name'] == PACKAGE)
                assert row['installed'] and not row['enabled']
                assert ctx.tools.get('python_echo') is None
            finally:
                await close(host)
        finally:
            await asyncio.get_running_loop().run_in_executor(None, server.shutdown)
            thread.join(timeout=5)

    assert not thread.is_alive()
    assert '/registry/@example%2Fpython-echo' in requests
    assert '/packages/@example/python-echo/0.1.0.tgz' in requests
