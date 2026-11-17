"""Current market listing service vs original installation/compatibility facts."""
import asyncio
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
URL = 'https://market.example/index.json'
RUNTIME = '0.2.2-rc.3'


def fixture():
    def release(version='1.0.0', **extra):
        return dict(version=version, publishTimestamp=1, source=dict(type='npm'), **extra)
    def entry(name, versions=None, **extra): return dict(name=name, versions=versions or [release()], **extra)
    def bundle(name, **extra): return dict(dict(name=name, installed=True, availability='profile'), **extra)
    plugins = [entry(name) for name in ['absent', 'same', 'older', 'newer', 'unknown', 'unparsed', 'shipped', 'shipped-unknown', 'catalog']]
    plugins[2]['versions'] = [release('2.0.0')]
    plugins += [entry('incompatible', [release(engines=dict(dsh='0.0.1'))]),
        entry('exempted', [dict(release(engines=dict(dsh='0.0.1')), source=dict(type='npm', registry='https://r.example/'))]),
        entry('mixed', [release('2.0.0-rc.1'), release('1.0.0'), release('1.1.0', engines=dict(dsh='0.0.1'))]),
        entry('previews', [release('1.0.0-beta.1'), release('1.0.0-rc.1', engines=dict(dsh='0.0.1'))]),
        entry('only-preview-stable', [release('2.0.0-rc.1'), release('1.0.0', engines=dict(dsh='0.0.1'))]),
        entry('build-precedence', [release('1.0.0+new')]), entry('runtime-match', [release(engines=dict(dsh=RUNTIME))])]
    versions = [dict(release(version), source=dict(type='git', url='https://git.example/o/plugins', commit=digit*40, path=path))
        for version, digit, path in [('1.3.0', 'd', 'packages/q'), ('1.2.0', 'c', 'packages/p'), ('1.0.0', 'a', 'packages/p'), ('0.9.0', '9', 'packages/p')]]
    versions.insert(2, release('1.1.0'))
    plugins += [entry(name, versions) for name in ['from-git', 'from-registry', 'no-source', 'no-version', 'unpinned']]
    plugins += [entry('hosted', [dict(release('1.1.0'), source=dict(type='git', url='https://github.com/o/plugins', commit='b'*40, path='p'))])]
    bundles = [bundle('same', version='1.0.0'), bundle('older', version='1.5.0'), bundle('newer', version='3.0.0'),
        bundle('unknown'), bundle('unparsed', version='local'), bundle('shipped', installed=False, availability='installation', version='1.0.0'),
        bundle('shipped-unknown', installed=False, availability='installation'), bundle('catalog', installed=False, availability='missing'),
        bundle('incompatible', version='0.9.0'), bundle('mixed', version='1.0.0'), bundle('build-precedence', version='1.0.0+old'),
        bundle('from-git', version='1.0.0', update='git', source='git+ssh://git@git.example/o/plugins.git#'+'a'*40+'&path:/packages/p'),
        bundle('from-registry', version='1.0.0', update='registry', source='from-registry@1.0.0'),
        bundle('no-source', version='1.0.0', update='git'), bundle('no-version', update='git', source='git+https://git.example/o/plugins.git#'+'a'*40+'&path:/packages/p'),
        bundle('unpinned', version='1.0.0', update='git', source='git+https://git.example/o/plugins.git#main&path:/packages/p'),
        bundle('hosted', version='1.0.0', update='git', source='github:o/plugins#'+'a'*40+'&path:/p')]
    for position, installed in enumerate([' 1.0.0 ', '\u00851.0.0\u0085', 'v1.0.0', '=1.0.0',
        '1.0.0+build', '1.0.0-01', '1.0.0-99999999999999999999', '1.0.0-foo', '1.0.0\n', '1.0.0\r', '1.0.0\ufeff']):
        name = 'version-spelling-'+str(position)
        plugins.append(entry(name, [release('2.0.0')])); bundles.append(bundle(name, version=installed))
    return dict(value=dict(format=1, title={'en': 'Market', 'zh': '市场'}, description='Bundles', plugins=plugins),
                bundles=bundles, exemptions={'exempted@1.0.0': [RUNTIME]})


async def observe():
    import dsh
    from dsh.boot.plugin_market_022 import CurrentPluginMarket
    from dsh.boot.market_index_022 import parse_market_index
    from dsh.cordis import Context
    from dsh.cordis.volatile import update_volatile, create_volatile
    data = fixture(); index = parse_market_index(data['value'], URL); ctx = Context(); rows = []; calls = []; manager_reads = []; writes = []
    async def bundles(): manager_reads.append(1); return data['bundles']
    async def update(identity, value): writes.append(dict(id=identity, patch=value))
    ctx.provide('pluginManager', SimpleNamespace(listBundles=bundles, listVersionExemptions=lambda: dict(exemptions=data['exemptions'])))
    ctx.provide('settings', SimpleNamespace(update=update))
    class Capture(CurrentPluginMarket):
        def __init__(self, inner, config):
            inner.fiber.entry = SimpleNamespace(options=dict(id='market'))
            super().__init__(inner, config)
    with patch.object(dsh, '__version__', RUNTIME):
        await ctx.plugin(Capture, dict(indexes=[URL], detailCacheDir='/nonexistent/plugin-market-detail-cache'))
        market = ctx.pluginMarket
        async def fetch(url, signal): calls.append(url); return index
        market.documents.fetch_index = fetch; market.documents.clock = lambda: 1000
        async def query(step, request=None, target=URL):
            try: value = await market.search(target, request or dict(sort=dict(kind='index'), offset=0, limit=100)); rows.append(dict(step=step, value=value))
            except Exception as error: rows.append(dict(step=step, error=dict(code=getattr(error, 'code', None), message=str(error), details=getattr(error, 'details', None))))
        try:
            await query('listing')
            await query('page', dict(sort=dict(kind='index'), offset=2, limit=3))
            await query('text', dict(text='preview', sort=dict(kind='relevance'), offset=0, limit=1))
            await query('empty-page', dict(sort=dict(kind='index'), offset=100, limit=1))
            rows.append(dict(step='single', value=await market.entry(URL, 'exempted')))
            rows.append(dict(step='unlisted', value=await market.entry(URL, 'unlisted')))
            data['bundles'][0]['version'] = '0.9.0'; await query('live-installation', dict(text='same', sort=dict(kind='relevance'), offset=0, limit=100))
            for key, values in [('offset', [-1, 1.5, 9007199254740992, True]), ('limit', [0, 101, 1.5, True])]:
                for value in values:
                    request = dict(sort=dict(kind='index'), offset=0, limit=1); request[key] = value; await query('invalid-'+key, request, 'https://unconfigured.example/')
            await query('unknown-index', target='https://unconfigured.example/')
            await market.setIndexes([URL, ' https://other.example:443/a ']); rows.append(dict(step='settings', writes=writes, indexes=market.listIndexes()))
            changed = []; ctx.on('plugin-market/changed', lambda: changed.append(1))
            update_volatile(market.config['indexes'], create_volatile([])); ctx.emit('loader/volatile-update', [['indexes']])
            rows.append(dict(step='removed', indexes=market.listIndexes(), changed=len(changed), fetches=len(calls), managerReads=len(manager_reads)))
        finally: await ctx.fiber.dispose()
    return rows


def prepare(output):
    import json
    path = output/'fixture.json'; path.write_text(json.dumps(fixture()), encoding='utf-8'); return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_listing.mts', scope='Original service search/entry annotations, page selection, live profile facts, query refusal order, settings and volatile events; controlled validated index fetch. Details and full Remote/application qualification excluded.',
        prepare=prepare, extra_inputs=[ROOT/'dsh/boot/market_listing_022.py', ROOT/'dsh/boot/plugin_market_022.py', ROOT/'scripts/rc022_market_listing_probe.py'])
