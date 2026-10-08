"""Official Web surface assembly over the owned server and Connection services."""
import asyncio
import logging
import os
import sys
import weakref
from pathlib import Path

from dsh.boot.app_boot import add_harness_source_section
from dsh.cordis.environment import launch_environment_of
from dsh.cordis.plugin import Plugin
from dsh.core.system_prompt import FIRST_PARTY_SECTION_ORDER
from dsh.host.frontend_static.frontend_static import FrontendStaticPlugin
from dsh.host.browser_compat.plugin import BrowserCompatibilityPlugin
from dsh.subprocess.service import scrubbed_parent_env

_announced = weakref.WeakSet()
SOURCE_ROOT = Path(__file__).resolve().parents[3]


def web_surface_prompt(url):
    return ('You are interacting with the user through the DeepSeek Harness Web GUI at ' + url + '. '
            'When the user refers to "this page", "this GUI", or "this app" without naming another target, they mean this GUI. '
            'The browser provides no implicit DOM, route, or screenshot context. '
            'The client-plugin HMR receiver is active, but client-plugin changes reload without a refresh only while '
            '`pnpm run dev:web` is also running from this same checkout to rebuild their bundles; verify that watcher before promising automatic updates. '
            'Every other change — the apps/web shell and plain packages — requires rebuilding the affected Web artifacts and verifying this existing URL after a page refresh. '
            'Starting another server does not update this GUI. '
            'The apps/web Vite entry builds the shell but is not a standalone application because only dsh web injects window.__DSH_BOOT__. '
            'Do not start a replacement server unless the user asks; if one is needed, use a managed background job and verify its exact URL.')


def local_url(ctx):
    server = ctx.get('webServer')
    if server is None:
        raise RuntimeError('web-app: webServer service missing while resolving Web runtime')
    return 'http://127.0.0.1:%s' % server.port


async def open_browser(url):
    # The helper gets a scrubbed environment and uses Win7 ShellExecute through
    # os.startfile. The authenticated URL is an argv value, never shell code.
    code = ('import os,sys; os.startfile(sys.argv[1])' if os.name == 'nt' else
            'import sys,webbrowser; sys.exit(0 if webbrowser.open(sys.argv[1]) else 1)')
    process = await asyncio.create_subprocess_exec(sys.executable, '-c', code, url,
        env=scrubbed_parent_env(), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
    try:
        _, stderr = await process.communicate()
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(stderr.decode('utf-8', 'replace').strip() or 'browser launcher failed')


class WebRuntimePlugin(Plugin):
    id = 'web-app'
    inject = ['webServer']

    async def apply(self, ctx):
        from dsh.bundle.web_app.trust import resolve_lan_trust
        config = dict(openBrowser=True, printUrl=True, surfaceContext=True, trustedHosts=[])
        config.update(self.config)
        for key in ('openBrowser', 'printUrl', 'surfaceContext'):
            if type(config[key]) is not bool:
                raise ValueError('web-app: %s must be a boolean' % key)
        if not isinstance(config['trustedHosts'], list) or any(not isinstance(v, str) for v in config['trustedHosts']):
            raise ValueError('web-app: trustedHosts must be an array of strings')
        runtime = resolve_lan_trust(ctx.get('webServer').host, config['trustedHosts'])
        ctx.set_service('webRuntime', runtime)
        await ctx.plugin(BrowserCompatibilityPlugin)
        await ctx.plugin(FrontendStaticPlugin, config={'distIndex': str(SOURCE_ROOT / 'apps/web/dist/index.html')})
        if config['surfaceContext']:
            def prompt(child):
                add_harness_source_section(child, str(SOURCE_ROOT))
                child.get('systemPrompt').section(dict(name='app:web-surface',
                    order=FIRST_PARTY_SECTION_ORDER.WEB_SURFACE, text=lambda *_: web_surface_prompt(local_url(child))))
            ctx.inject(['systemPrompt'], prompt)
            def environment(child):
                child.get('shellEnv').register(dict(name='web-runtime',
                    variables={'DSH_WEB_URL': {'description': 'Canonical local URL of the DeepSeek Harness Web GUI serving this session.'}},
                    resolve=lambda *_: {'DSH_WEB_URL': local_url(child)}))
            ctx.inject(['shellEnv'], environment)
        environment = launch_environment_of(ctx)
        ssh = any(getattr(environment.get_from(key, ['process']), 'value', '') for key in ('SSH_CONNECTION', 'SSH_TTY'))
        handoff = config['openBrowser'] and not ssh
        if not config['printUrl'] and not handoff:
            return
        def connection_ready(child):
            ready = child.get('appReady')
            async def announce():
                loader = child.get('loader')
                if ready is None and loader is not None:
                    try:
                        # Cancelling this observer must never cancel shared
                        # Loader activation tasks that await_ joins.
                        await asyncio.shield(loader.await_())
                    except Exception:
                        return
                connection, server = child.get('connection'), child.get('webServer')
                if connection is None or server is None or child.root in _announced:
                    return
                _announced.add(child.root)
                url = connection.authenticated_url(local_url(child))
                if config['printUrl']:
                    suffix = ''
                    if runtime['lanAddresses']:
                        suffix = ' (LAN: %s)' % connection.authenticated_url('http://%s:%s' % (runtime['lanAddresses'][0], server.port))
                    print('dsh web: ' + url + suffix, flush=True)
                if handoff:
                    print('dsh web: opening the default browser; pass --no-open to disable', flush=True)
                    try:
                        await open_browser(url)
                    except Exception as error:
                        logging.getLogger('web-app').warning('could not open the default browser because %s; use the dsh web URL printed at startup', error)
            tasks = []
            def start():
                tasks.append(asyncio.create_task(announce()))
            unsubscribe = ready.on_ready(start) if ready is not None else None
            if ready is None:
                start()
            async def close():
                if unsubscribe is not None:
                    unsubscribe()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            child.effect(lambda: close)
        ctx.inject(['connection'], connection_ready)
