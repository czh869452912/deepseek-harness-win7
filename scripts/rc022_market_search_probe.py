"""Repeated and concurrent persistent-worker queries against pinned Source search."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_market_index_probe import cases

OUTPUT = None


def prepare(output):
    global OUTPUT
    OUTPUT = output
    rows = [row for row in cases() if row['kind'] == 'search']
    for row in rows:
        row['selections'] += row['selections'][:2]
    path = output/'input.json'
    path.write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    return [path]


async def native():
    from dsh.boot.market_search_022 import MarketSearchWorker
    from dsh.core.abort import AbortController
    pool = MarketSearchWorker(AbortController().signal)
    rows = []
    try:
        for revision, row in enumerate(json.loads((OUTPUT/'input.json').read_text(encoding='utf-8'))):
            document = dict(index=row['value'], fetchedAt=revision+1)
            pool.retain({row['url']:dict(document=document)})
            results = await asyncio.gather(*(pool.select(row['url'], document, selection) for selection in row['selections']))
            rows.append(dict(ok=True, results=results))
    finally:
        await pool.dispose()
    return rows


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'.goose/out/rc022-prep-20261114-01/source'
    probe.main('rc022_market_index.mts', 'Persistent Source MarketSearch reuse, concurrent/repeated multilingual, taxonomy, ordering and 1001-document chunked queries.',
        [Path(__file__).resolve(), ROOT/'dsh/boot/market_search_022.py', ROOT/'dsh/boot/market-index/manifest.json',
         ROOT/'scripts/native/market-index/search-driver.js', source/'packages/boot/plugin-market/src/search.ts'], prepare)
