"""Socket-free desktop composition over the canonical Connection and Gateway."""
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dsh.boot.app_boot import boot, load_layered_env
from dsh.boot.cmdline import provide_cmdline
from dsh.boot.profile import (init_profile, load_profile_directory, heal_profiles_module_fallback)
from dsh.boot.profile_boot import INSTALL_ANCHOR, admit_historical_persona_patches
from dsh.boot.profile_lease import ProfileLease
from dsh.boot.python_plugin_dependencies import PythonDependencyLease
from dsh.cordis.environment import DSH_LAUNCH_ENVIRONMENT_KEY
from dsh.cordis.json_text import stringify_json
from dsh.host.browser_compat.plugin import BrowserCompatibilityPlugin
from dsh.host.frontend_static.frontend_static import MIME_TYPES
from dsh.host.http_proxy import install_proxy_from_environment
from dsh.host.webserver.injections import render_index_injections

ROOT = Path(__file__).resolve().parents[3]
STREAM_PATH = '/.dsh/remote-stream'
MAX_BODY = 128 * 1024 * 1024


async def body_bytes(body, maximum=MAX_BODY):
    if body is None:
        return b''
    if isinstance(body, (bytes, bytearray)):
        if len(body) > maximum:
            raise ValueError('desktop request body exceeds its byte limit')
        return bytes(body)
    parts, size = [], 0
    async for chunk in body:
        size += len(chunk)
        if size > maximum:
            raise ValueError('desktop request body exceeds its byte limit')
        parts.append(chunk)
    return b''.join(parts)


def result(status, body=None, headers=None):
    return dict(status=status, body=body, headers=headers or {})


class DesktopRuntime:
    def __init__(self, ctx, release, dist=None):
        self.ctx, self.release = ctx, release
        self.dist = (Path(dist) if dist else ROOT / 'apps/web/dist').resolve()
        self.api = ctx.get('connection').createSharedFetchHandler('/api')
        self.closed = False

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            await self.ctx.serial('app/stopping')
            await self.ctx.fiber.dispose()
            await self.ctx.fiber.await_settled()
        finally:
            await self.release()

    async def fetch(self, request):
        if self.closed:
            raise RuntimeError('dsh desktop: host is disposing')
        url = urlsplit(request['url'])
        if url.scheme != 'dsh-app' or url.netloc != 'app':
            return result(403)
        request = dict(request, path=url.path, query=url.query, raw_url=url.path + ('?' + url.query if url.query else ''))
        signal = request['signal']
        signal.throwIfAborted()
        if url.path == STREAM_PATH:
            if request['method'] != 'POST':
                return result(405)
            try:
                payload = json.loads(await body_bytes(request.get('body'), 1024 * 1024))
            except (ValueError, UnicodeError):
                return result(400)
            if not isinstance(payload, dict) or not isinstance(payload.get('endpoint'), str) or 'payload' not in payload:
                return result(400)
            async def stream():
                iterator = await self.ctx.get('typertGateway').wireStream.open(payload['endpoint'], payload['payload'], signal)
                try:
                    async for item in iterator:
                        signal.throwIfAborted()
                        yield (stringify_json(item) + '\n').encode('utf-8')
                finally:
                    if hasattr(iterator, 'aclose'):
                        await iterator.aclose()
            return result(200, stream(), {'content-type': 'application/x-ndjson'})
        if url.path.startswith('/api/'):
            if self.api.requestBodyMode(request) != 'streaming':
                request['body'] = await body_bytes(request.get('body'))
            return await self.api.fetch(request)
        if request['method'] not in ('GET', 'HEAD'):
            return result(405)
        if url.path.startswith('/plugins/'):
            return self.ctx.get('clientModules').fetchBundle(request)
        try:
            path = unquote(url.path, errors='strict')
            target = (self.dist / path.lstrip('/')).resolve()
            target.relative_to(self.dist)
        except (ValueError, UnicodeError):
            return result(403)
        if path in ('/', '/index.html'):
            if request['method'] == 'HEAD':
                return result(200, headers={'content-type': MIME_TYPES['.html']})
            rows = [dict(kind='script', placement='head', text=(ROOT / 'apps/desktop-host/transport.js').read_text(encoding='utf-8'))]
            self.ctx.emit('webserver/index-inject', rows)
            html = render_index_injections((self.dist / 'index.html').read_text(encoding='utf-8'), rows)
            html = self.ctx.get('browserCompatibility').validate_index(html)
            return result(200, html.encode('utf-8'), {'content-type': MIME_TYPES['.html']})
        if not target.is_file():
            return result(404)
        return result(200, None if request['method'] == 'HEAD' else target.read_bytes(),
                      {'content-type': MIME_TYPES.get(target.suffix, 'application/octet-stream')})


async def run_desktop_host(profile_dir, environment=None, patches=None):
    """Application-owned profile; reuse canonical loading, activation and leases."""
    directory = Path(profile_dir).resolve()
    with ProfileLease(str(directory), exclusive=True):
        from dsh.boot.python_plugins import recover
        recover(str(directory))
        init_profile(str(directory), ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'])
    lease, dependencies, dispose_proxy, ctx = ProfileLease(str(directory)), None, None, None
    async def release():
        try:
            if dispose_proxy is not None:
                await dispose_proxy()
        finally:
            try:
                if dependencies is not None:
                    dependencies.close()
            finally:
                lease.close()
    try:
        dependencies = PythonDependencyLease(str(directory))
        environment = environment if environment is not None else load_layered_env('dsh desktop')
        dispose_proxy = await install_proxy_from_environment(environment, lambda message: sys.stderr.write('dsh desktop: ' + message + '\n'))
        profile = load_profile_directory('dsh desktop', str(directory), INSTALL_ANCHOR)
        await heal_profiles_module_fallback(dict(installAnchor=INSTALL_ANCHOR, profile=profile))
        rows = [row for layer in profile.layers for row in layer.patches] + profile.patches
        rows += [dict(id=identity, disabled=True) for identity in
                 ('web-startup', 'webserver', 'web-runtime', 'client-hmr', 'open-in-app', 'ui-open-in-app', 'directory-picker')]
        rows += [dict(id='connection', inject=['credentials'], config={}), dict(insert=[
            dict(id='directory-picker-native', name='@deepseek-ai/dsh-host-directory-picker-native'),
            dict(id='ui-directory-picker-native', name='@deepseek-ai/dsh-client-ui-directory-picker-native')])]
        if os.environ.get('DSH_TELEMETRY_DISABLED'):
            rows.append(dict(id='session-telemetry-otel', disabled=True))
        rows += patches or []
        from dsh.boot.session_compatibility import preserve_default_session_encoding
        rows = await asyncio.get_running_loop().run_in_executor(None, preserve_default_session_encoding, rows)
        root_config = directory / 'desktop.cordis.yml'
        root_config.write_text('# Desktop composition root; user overrides belong in cordis.patch.yml.\n[]\n', encoding='utf-8')
        def prepare(host):
            host.provide(DSH_LAUNCH_ENVIRONMENT_KEY, environment)
            provide_cmdline(host, dict(args=[], exit=lambda code: None))
        ctx = await boot('dsh desktop', str(root_config), admit_historical_persona_patches(rows), prepare)
        await ctx.plugin(BrowserCompatibilityPlugin)
        for name in ('connection', 'typertGateway', 'clientModules'):
            if ctx.get(name) is None:
                raise RuntimeError('dsh desktop: composition did not provide ' + name)
        if ctx.get('webServer') is not None:
            raise RuntimeError('dsh desktop: socket carrier unexpectedly mounted')
        return DesktopRuntime(ctx, release)
    except BaseException:
        try:
            if ctx is not None:
                await ctx.fiber.dispose()
                await ctx.fiber.await_settled()
        finally:
            await release()
        raise
