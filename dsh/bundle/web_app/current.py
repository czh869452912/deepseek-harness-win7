"""Current Web runtime: advertised origin, static owner and readiness handoff."""
import asyncio
import logging
import re
import weakref
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlsplit

from dsh.boot.plugin_install_spec import _url_host
from dsh.boot.startup import audit_startup_entries
from dsh.cordis.environment import launch_environment_of
from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.host.frontend_static.current import CurrentFrontendStatic
from dsh.host.browser_compat.plugin import BrowserCompatibilityPlugin
from dsh.host.webserver.bind import bind_url_host, is_loopback_host
from dsh.bundle.web_app.runtime import open_browser

_announced = weakref.WeakSet()


def parse_public_url(value, label='publicUrl'):
    def reject(reason): raise ValueError(label+' '+reason)
    if re.search(r'[\x00-\x20\x7f]', value):
        reject('must not contain ASCII whitespace or control characters')
    if not re.match(r'^https?://', value, re.IGNORECASE | re.ASCII):
        reject('must be an absolute http or https URL of the form http(s)://host[/prefix]')
    if '?' in value or '#' in value:
        reject('must not include a query or fragment (? or #)')
    authority = re.split(r'[/\\]', value[value.index('://')+3:], maxsplit=1)[0]
    if not authority: reject('must name a host after http:// or https://')
    if '@' in authority:
        reject('must not include credentials (a username or password before @, including an empty user)')
    try:
        normalized = value.replace('\\', '/')
        host = _url_host(normalized)
        parsed = urlsplit(normalized)
    except (ValueError, TypeError):
        reject('must be an absolute http or https URL')
    # WHATWG special-URL path shortening includes percent-encoded dot segments.
    segments = []
    for part in (parsed.path or '/').split('/')[1:]:
        dot = re.sub('%2e', '.', part, flags=re.IGNORECASE)
        if dot == '..':
            if segments: segments.pop()
        elif dot != '.': segments.append(part)
    path = '/'+ '/'.join(segments)
    if not path.endswith('/'): path += '/'
    path = path.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace')
    path = quote(path, safe="!$&'()*+,-./:;=@[]_%|", encoding='utf-8')
    return parsed.scheme.lower()+'://'+host+path


CONFIG = z.object(dict(openBrowser=z.boolean().default(True), printUrl=z.boolean().default(True),
    surfaceContext=z.boolean().default(True), publicUrl=z.transform(z.string(), parse_public_url)))


def resolve_dist_index():
    return str(Path(__file__).resolve().parents[3]/'apps/web/dist/index.html')


class CurrentWebRuntime(Plugin):
    id = 'web-app'
    inject = ['webServer']
    Config = CONFIG

    async def apply(self, ctx):
        config = self.config
        public = config.get('publicUrl')
        server = ctx.webServer
        if public is None and bind_url_host(server.host) is None:
            raise ValueError('web-app: bind address '+stringify_json(server.host)+' carries an interface zone id, which no URL can express; pass --public-url with the root browsers actually reach it through')
        if server.protocol == 'http:' and not is_loopback_host(server.host):
            logging.getLogger('web-app').warning('dsh web: listening on %s over plain HTTP; restrict this port to a trusted proxy or network', server.host)
        def advertised(): return public if public is not None else ctx.webServer.getOrigin()
        ctx.set_service('webApp', SimpleNamespace(getAdvertisedUrl=advertised))
        await ctx.plugin(BrowserCompatibilityPlugin)
        await ctx.plugin(CurrentFrontendStatic, config=dict(distIndex=resolve_dist_index()))
        if config['surfaceContext']:
            def environment(child):
                child.shellEnv.register(dict(name='web-runtime', variables=dict(DSH_WEB_URL=dict(
                    description='Advertised URL of the DeepSeek Harness Web GUI serving this session.')),
                    resolve=lambda *_:dict(DSH_WEB_URL=advertised())))
            ctx.inject(['shellEnv'], environment)
        snapshot = launch_environment_of(ctx)
        ssh = any(getattr(snapshot.get_from(key, ['process']), 'value', '') for key in ('SSH_CONNECTION', 'SSH_TTY'))
        handoff = config['openBrowser'] and not ssh
        if not config['printUrl'] and not handoff: return
        def connection_ready(child):
            async def announce():
                loader = child.get('loader')
                if loader is not None:
                    try:
                        await asyncio.shield(loader.await_())
                        await audit_startup_entries(child.root, 'dsh web', lambda _:None)
                    except Exception: return
                if child.get('webServer') is None or child.get('connection') is None or child.root in _announced: return
                url = child.connection.authenticatedUrl(advertised())
                _announced.add(child.root)
                if config['printUrl']: print('dsh web: '+url, flush=True)
                if handoff:
                    print('dsh web: opening the default browser; pass --no-open to disable', flush=True)
                    try: await open_browser(url)
                    except Exception as error:
                        logging.getLogger('web-app').error('web-app: could not open the default browser because %s; use the dsh web URL printed at startup', error)
            task = asyncio.create_task(announce())
            async def close():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            child.effect(lambda: close)
        ctx.inject(['connection'], connection_ready)
