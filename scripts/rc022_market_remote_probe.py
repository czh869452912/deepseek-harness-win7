"""Market detail Remote, real readers and image route compared with pinned Source."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
URL = 'https://market.example/index.json'
COMMIT = 'b'*40
DIRECTORY = None


def fixture():
    plugins = []
    def add(name, source, repository=None):
        row = dict(name=name, versions=[dict(version='1.0.0', publishTimestamp=1, source=source, engines=dict(dsh='*'))])
        if repository is not None: row['repository'] = repository
        plugins.append(row)
    add('git', dict(type='git', url='https://github.com/o/r', commit=COMMIT, path='pkg'))
    add('self', dict(type='git', url='https://github.com/o/self', commit=COMMIT, path='pkg'), dict(url='https://github.com/o/self', directory='pkg'))
    add('npm', dict(type='npm'))
    add('private', dict(type='npm', registry='https://npm.corp.example/'), dict(url='https://github.com/o/private'))
    add('manifest', dict(type='npm'))
    add('none', dict(type='npm', registry='https://npm.corp.example/'))
    add('bad', dict(type='git', url='https://github.com/o/bad', commit=COMMIT))
    routes = {'https://raw.githubusercontent.com/o/r/'+COMMIT+'/pkg/locale/zh.json': dict(meta=dict(detail='guide.md')),
        'https://raw.githubusercontent.com/o/r/'+COMMIT+'/pkg/guide.md': '# 中文\n![image](img/a.png)',
        'https://raw.githubusercontent.com/o/r/'+COMMIT+'/pkg/img/a.png': [137, 80, 78, 71, 10],
        'https://cdn.jsdelivr.net/npm/npm@1.0.0/README.md': '# Npm',
        'https://raw.githubusercontent.com/o/private/HEAD/README.md': '# Private repository',
        'https://cdn.jsdelivr.net/npm/manifest@1.0.0/package.json': dict(repository=dict(url='https://github.com/o/manifest', directory='docs')),
        'https://raw.githubusercontent.com/o/manifest/HEAD/docs/README.md': '# Manifest repository',
        'https://raw.githubusercontent.com/o/bad/'+COMMIT+'/locale/en.json': dict(meta=dict(detail='../bad.md'))}
    return dict(index=dict(format=1, title='Market', plugins=plugins), routes=routes)


async def observe_fixture(directory):
    from dsh.boot.plugin_market_022 import CurrentPluginMarket
    from dsh.boot.market_index_022 import parse_market_index
    from dsh.cordis import Context
    from dsh.typert.dispatch import original_of
    data = fixture(); ctx = Context(); calls, rows, routes = [], [], {}
    async def bundles(): return []
    ctx.provide('pluginManager', SimpleNamespace(listBundles=bundles, listVersionExemptions=lambda: dict(exemptions={})))
    def register(route):
        routes[route['path']] = route
        def remove(): routes.pop(route['path'], None)
        return remove
    ctx.provide('connection', SimpleNamespace(fetch=SimpleNamespace(register=register)))
    async def fetch(url, maximum, signal, options):
        calls.append(url); value = data['routes'].get(url)
        if value is None: return dict(ok=False, status=404)
        body = bytes(value) if isinstance(value, list) else (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).encode('utf-8')
        return dict(ok=True, bytes=body)
    async def public(url): return True
    with patch('dsh.util.plugin_detail_http.fetch_body', fetch), patch('dsh.boot.market_repository_files_022.fetch_body', fetch):
        try:
            await ctx.plugin(CurrentPluginMarket, dict(indexes=[URL], detailCacheDir=str(directory)))
            market = original_of(ctx.pluginMarket); market.repositories.isPublic = public
            async def index(*_): return parse_market_index(data['index'], URL)
            market.documents.fetch_index = index
            async def step(name, language='en', options=None, version='1.0.0', target=URL):
                try:
                    value = await market.readEntryDetail(target, name, version, language, options)
                    rows.append(dict(step=name, value=value, fetches=len(calls)))
                    return value
                except Exception as error:
                    rows.append(dict(step=name, error=dict(code=getattr(error, 'code', None), message=str(error), details=getattr(error, 'details', None)), fetches=len(calls)))
            first = await step('git', 'zh-CN')
            await step('git', 'zh-CN'); await step('git', 'zh-CN', dict(refresh=True))
            for name in ('npm', 'private', 'manifest', 'none', 'self', 'bad', 'missing'):
                await step(name)
            await step('npm', version='9.0.0'); await step('npm', language='../en', target='https://unknown.example/')
            for suffix in ['?document='+first['document']+'&path=img/a.png', '?document='+first['document']+'&path=../escape.png',
                           '?document=missing&path=a.png', '?document=x']:
                response = await routes['/api/plugin-market/detail-file']['fetch'](dict(url='https://app.example/api/plugin-market/detail-file'+suffix))
                body = response['body']; body = body.encode('utf-8') if isinstance(body, str) else body
                rows.append(dict(step='image', status=response['status'], headers={key.lower():value for key, value in response['headers'].items()}, body=list(body)))
            rows.append(dict(step='route', paths=list(routes), calls=calls))
        finally:
            await ctx.fiber.dispose()
    rows.append(dict(step='disposed', paths=list(routes)))
    return rows


async def observe():
    return await observe_fixture(DIRECTORY/'native-cache')


def prepare(output):
    global DIRECTORY
    DIRECTORY = output/'files'; DIRECTORY.mkdir()
    path = output/'fixture.json'; path.write_text(json.dumps(dict(fixture(), directory=str(DIRECTORY))), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_remote.mts', scope='Actual Market readEntryDetail and shared file readers over controlled HTTP: pinned Git/locales, public npm, private registry fallback, manifest fallback, duplicate repository suppression, cached/refresh IDs, Remote error ordering and reversible adjacent-image route.',
        prepare=prepare, extra_inputs=[ROOT/'dsh/boot/plugin_market_022.py', Path(__file__).resolve()])
