"""Controlled package files prove detail cache/image ownership against Source."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.boot.market_detail_022 import MarketDetailReader
    from dsh.util.plugin_detail import DetailFailure, readme_name
    from dsh.core.abort import AbortController
    rows = []; now = [1000]
    class Memory:
        def __init__(self, key, values): self.key, self.values, self.reads = key, values, []
        async def read(self, path, maximum, signal):
            self.reads.append(path); signal.throwIfAborted(); value = self.values.get(path)
            if isinstance(value, Exception): raise value
            if value is None: return None
            data = value.encode('utf-8')
            if len(data) > maximum: raise DetailFailure('too-large', path)
            return data
        async def readme(self, directory, maximum, signal):
            prefix = directory+'/' if directory else ''
            name = readme_name([path[len(prefix):] for path in self.values if path.startswith(prefix) and '/' not in path[len(prefix):]])
            if name is None: return None
            path = prefix+name; data = await self.read(path, maximum, signal)
            return dict(path=path, bytes=data)
    lifetime = AbortController()
    def forbidden(*_): raise AssertionError('No repository fixture in this cache batch')
    reader = MarketDetailReader(dict(maxDocumentBytes=100, maxImageBytes=10, ttlMs=1000),
        dict(lifetime=lifetime.signal), forbidden, forbidden, lambda: now[0])
    async def step(name, work):
        try:
            value = await work()
            if isinstance(value, dict) and isinstance(value.get('bytes'), bytes): value = dict(value, bytes=list(value['bytes']))
            rows.append(dict(step=name, value=value))
            return value
        except Exception as error:
            rows.append(dict(step=name, error=dict(reason=getattr(error, 'reason', None), message=str(error))))
    files = Memory('npm:a@1', {'locale/en.json': json.dumps(dict(meta=dict(detail='guide/DETAIL.md'))),
        'guide/DETAIL.md': '# Detail', 'guide/img/a.png': 'png', 'logo.SVG': '<svg/>', 'guide/a b.webp': 'webp', 'guide/big.gif': 'x'*20})
    location = dict(files=files, dir='')
    a, b = await asyncio.gather(reader.read(location, ['zh', 'en']), reader.read(location, ['zh', 'en']))
    rows.append(dict(step='shared', same=a is b, value=a, reads=list(files.reads)))
    await step('cached', lambda: reader.read(location, ['zh', 'en']))
    for authored in ['img/a.png?raw=1#x', '/logo.SVG', './a%20b.webp', '../../escape.png', 'notes.txt', 'img/missing.png', 'big.gif']:
        await step('image:'+authored, lambda authored=authored: reader.image(a['document'], authored))
    await step('unknown-id', lambda: reader.image('unknown', 'a.png'))
    idle = Memory('npm:idle@1', {'README.md': '# Idle', 'a.png': 'png'})
    value = await step('idle', lambda: reader.read(dict(files=idle, dir=''), ['en']))
    now[0] += 600; await step('keep-image', lambda: reader.image(a['document'], 'img/a.png'))
    now[0] += 600; await step('kept-image', lambda: reader.image(a['document'], 'img/a.png'))
    await step('expired-id', lambda: reader.image(value['document'], 'a.png'))
    await step('same-id-restored', lambda: reader.read(dict(files=idle, dir=''), ['en']))
    now[0] += 1000; await step('exact-ttl-image', lambda: reader.image(value['document'], 'a.png'))
    await step('refresh', lambda: reader.read(location, ['zh', 'en'], True))
    for reason in ['too-large', 'denied', 'invalid', 'network', 'git-unavailable']:
        broken = Memory(reason, {'locale/en.json': DetailFailure(reason, 'failure '+reason)})
        for _ in range(2): await step('failure:'+reason, lambda: reader.read(dict(files=broken, dir=''), ['en']))
        rows.append(dict(step='failure-reads:'+reason, reads=len(broken.reads)))
    missing = Memory('missing', {'locale/en.json': json.dumps(dict(meta=dict(detail='GONE.md')))})
    await step('missing-declared', lambda: reader.read(dict(files=missing, dir=''), ['en']))
    empty = Memory('empty', {})
    await step('none', lambda: reader.read(dict(files=empty, dir=''), ['en']))
    await step('none-cached', lambda: reader.read(dict(files=empty, dir=''), ['en']))
    rows.append(dict(step='settled', pending=len(reader.pending)))
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_detail.mts', scope='Detail package-first selection, deterministic document identity, shared/TTL/refresh/error cache, image path/type/size and id use/expiry; in-memory files only, repository resolution and transport excluded.',
        extra_inputs=[ROOT/'dsh/boot/market_detail_022.py', ROOT/'scripts/rc022_market_detail_probe.py'])
