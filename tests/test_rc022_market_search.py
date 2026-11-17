import asyncio
import json
import os
from pathlib import Path
import subprocess

import pytest

from dsh.boot import market_search_022 as search
from dsh.boot.market_index_022 import observe_market_operations_async
from dsh.core.abort import AbortController
from dsh.javascript.runtime import JavaScriptRuntimeError


URL = 'https://market.example/index.json'


def document(identity=1, prefix='entry', count=1101):
    return dict(fetchedAt=identity, index=dict(format=1, title='Search', plugins=[dict(
        name=prefix+'-'+str(position), title='中文搜索 '+str(position), description='searchable fixture',
        versions=[dict(version='1.0.0', publishTimestamp=1700000000, engines=dict(dsh='*'),
                       source=dict(type='npm'))]) for position in range(count)]))


async def until(predicate):
    async def wait():
        while not predicate(): await asyncio.sleep(.001)
    await asyncio.wait_for(wait(), 5)


@pytest.mark.asyncio
async def test_real_chunked_search_reuses_process_and_retires_refreshed_documents():
    controller = AbortController(); pool = search.MarketSearchWorker(controller.signal)
    first = document(); other = document(2, 'replacement', 2)
    selections = [dict(text=text, sort=dict(kind='relevance')) for text in ('中文', 'searchabl', 'entry-99', '   ', 'fixture', '搜索')]
    expected = (await observe_market_operations_async([dict(kind='search', value=first['index'], url=URL, selections=selections)]))[0]['results']
    try:
        pool.retain({URL:dict(document=first)})
        actual = await asyncio.gather(*(pool.select(URL, first, selection) for selection in selections))
        assert actual == expected
        worker = pool.worker; start = pool.starting
        assert worker.process.returncode is None and len(pool.known) == 1
        assert await pool.select(URL, first, selections[0]) == expected[0]
        assert pool.worker is worker and pool.starting is start
        pool.retain({URL:dict(document=other)})
        assert await pool.select(URL, other, dict(sort=dict(kind='index'))) == ['replacement-0', 'replacement-1']
        await until(lambda: not pool.active)
        await pool._prune()
        assert pool.known == {search.document_key(URL, other)}
        pool.retain({})
        await pool._prune()
        assert not pool.known
    finally:
        await pool.dispose()
    assert pool.worker.process.returncode is not None
    assert not pool.jobs and not pool.pending and not pool.active


@pytest.mark.asyncio
async def test_cancelled_caller_keeps_shared_worker_and_other_reader_alive(monkeypatch):
    monkeypatch.setattr(search, 'market_bootstrap', lambda: '''
globalThis.__marketIndex={openSearch:()=>selection=>{
 if(selection.text==='hold')return new Promise(resolve=>globalThis.releaseHeld=resolve);
 if(globalThis.releaseHeld)globalThis.releaseHeld(['held-completed']);
 return Promise.resolve(['live']);
}};
''')
    pool = search.MarketSearchWorker(AbortController().signal); doc = document(count=0)
    task = asyncio.create_task(pool.select(URL, doc, dict(text='hold')))
    try:
        await until(lambda: bool(pool.pending))
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert pool.worker.process.returncode is None
        assert await pool.select(URL, doc, dict(text='release')) == ['live']
        await until(lambda: not pool.pending)
    finally:
        await pool.dispose()
    assert pool.worker.process.returncode is not None and not pool.jobs


@pytest.mark.asyncio
async def test_lifetime_abort_and_operation_deadline_reap_shared_process(monkeypatch):
    monkeypatch.setattr(search, 'market_bootstrap', lambda: 'globalThis.__marketIndex={openSearch:()=>()=>new Promise(()=>{})};')
    controller = AbortController(); pool = search.MarketSearchWorker(controller.signal)
    reason = RuntimeError('owner lifetime ended')
    task = asyncio.create_task(pool.select(URL, document(count=0), {}))
    await until(lambda: bool(pool.pending))
    controller.abort(reason)
    with pytest.raises(RuntimeError) as caught: await task
    assert caught.value is reason
    await pool.dispose()
    assert pool.worker.process.returncode is not None and not pool.jobs
    timed = search.MarketSearchWorker(AbortController().signal, timeout=.05)
    with pytest.raises(JavaScriptRuntimeError, match='operation deadline'):
        await timed.select(URL, document(count=0), {})
    assert timed.closed and timed.worker.process.returncode is not None and not timed.jobs


@pytest.mark.asyncio
async def test_abort_during_spawn_owns_delayed_process(monkeypatch):
    original = asyncio.create_subprocess_exec
    spawned = asyncio.Event(); release = asyncio.Event(); children = []
    async def delayed(*args, **kwargs):
        child = await original(*args, **kwargs); children.append(child)
        spawned.set(); await release.wait(); return child
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed)
    controller = AbortController(); pool = search.MarketSearchWorker(controller.signal)
    task = asyncio.create_task(pool.select(URL, document(count=0), {}))
    await asyncio.wait_for(spawned.wait(), 5)
    reason = RuntimeError('abort while opening')
    controller.abort(reason); release.set()
    with pytest.raises(RuntimeError) as caught: await task
    assert caught.value is reason
    await pool.dispose()
    assert children and all(child.returncode is not None for child in children)
    assert not pool.jobs


def test_x86_persistent_worker_matches_x64_queries():
    executable = os.environ.get('DSH_TEST_X86_PYTHON')
    if not executable: pytest.skip('explicit x86 Python fixture not configured')
    script = '''import asyncio,ctypes,json,os,sys
sys.path.insert(0,os.getcwd())
from dsh.boot.market_search_022 import MarketSearchWorker
from dsh.core.abort import AbortController
from scripts.rc022_market_index_probe import cases
assert ctypes.sizeof(ctypes.c_void_p)==4
async def run():
 pool=MarketSearchWorker(AbortController().signal)
 rows=[]
 try:
  for revision,row in enumerate([r for r in cases() if r['kind']=='search']):
   doc=dict(index=row['value'],fetchedAt=revision+1)
   pool.retain({row['url']:dict(document=doc)})
   rows.append(await asyncio.gather(*(pool.select(row['url'],doc,s) for s in row['selections'])))
 finally: await pool.dispose()
 assert pool.worker.process.returncode is not None
 return rows
print(json.dumps(asyncio.run(run()),ensure_ascii=True))
'''
    result = subprocess.run([executable, '-c', script], cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')[-2000:]
    from scripts.rc022_market_index_probe import cases
    async def expected():
        operations = [row for row in cases() if row['kind'] == 'search']
        return [row['results'] for row in await observe_market_operations_async(operations)]
    assert json.loads(result.stdout) == asyncio.run(expected())
