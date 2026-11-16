"""Paired store policies through actual store methods and controlled providers."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

MODES = ['normal', 'cached', 'oversized', 'mismatch', 'quota', 'quota-empty', 'quota-repeat',
         'winner', 'winner-cleanup-fail', 'release', 'release-missing', 'reclaim', 'release-all', 'invalidate']


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(MODES), encoding='utf-8'); return [path]


async def observe():
    from dsh.llm.deepseek_file_store_current import DeepSeekFileStore, fileScope
    from dsh.llm.deepseek_files_current import DeepSeekFilesError
    rows = []
    for mode in MODES:
        events = []; uploads = 0; lists = 0
        connection = dict(baseURL='https://example.test/anthropic/', headers={'Z-Key': 'z', 'a-Key': 'a'})
        version = dict(attachment=dict(attachmentId='sha256:'+'a'*64), variantId='sha256:'+'b'*64,
                       bytes=33554433 if mode == 'oversized' else 3, data=b'abc', mediaType='image/png')
        policy = dict(expiresAfterSeconds=3600, refreshMarginSeconds=10, quotaCleanupBatch=2)
        cached = dict(scope=fileScope(connection), attachmentId=version['attachment']['attachmentId'],
                      variantId=version['variantId'], fileId='cached', bytes=3, createdAt=1000, expiresAt=4000000)
        async def get(scope, variant, now, margin):
            events.append(dict(get=[scope, variant, now, margin]))
            return cached if mode in ('cached', 'release') else None
        async def commit(candidate, now, margin):
            events.append(dict(commit=candidate, now=now, margin=margin))
            return dict(record=cached if mode.startswith('winner') else candidate, accepted=not mode.startswith('winner'))
        async def remove(scope, generations): events.append(dict(remove=[scope, generations]))
        async def clear(scope): events.append(dict(clear=scope))
        async def upload(**input):
            nonlocal uploads
            uploads += 1
            events.append(dict(upload=dict(filename=input['filename'], expiry=input['expiresAfterSeconds'], bytes=len(input['data']))))
            if mode.startswith('quota') and (uploads == 1 or mode == 'quota-repeat'):
                raise DeepSeekFilesError('quota', 400, 'storage quota')
            return dict(id='uploaded', bytes=4 if mode == 'mismatch' else 3, createdAt=2, expiresAt=3602)
        async def delete(fileId, signal=None):
            events.append(dict(delete=fileId))
            if mode == 'winner-cleanup-fail': raise RuntimeError('cleanup unavailable')
        async def listing(after=None, limit=None, signal=None):
            nonlocal lists
            lists += 1; events.append(dict(list=dict(after=after, limit=limit)))
            if mode == 'quota-empty' or mode == 'release-all' and lists > 2: return dict(data=[], hasMore=False)
            if after is None:
                return dict(data=[dict(id='newer', createdAt=30, filename='dsh-new'),
                                  dict(id='foreign', createdAt=0, filename='other'),
                                  dict(id='middle', createdAt=20, filename='dsh-mid')], hasMore=True, lastId='cursor')
            return dict(data=[dict(id='oldest', createdAt=1, filename='dsh-old'),
                              dict(id='tied', createdAt=20, filename='dsh-tie')], hasMore=True, lastId='cursor')
        store = DeepSeekFileStore(index=SimpleNamespace(get=get, commit=commit, remove=remove, clear=clear),
                                  now=lambda: 10000, client_factory=lambda _: SimpleNamespace(upload=upload, delete=delete, list=listing))
        try:
            if mode.startswith('release-') or mode == 'release':
                value = await (store.releaseAll(connection) if mode == 'release-all' else store.release(version, connection, policy))
            elif mode == 'reclaim': value = await store.reclaimOldestOwned(connection, 2)
            elif mode == 'invalidate': value = await store.invalidate([dict(variantId=version['variantId'], fileId='old')], connection)
            else: value = await store.ensureUploaded(version, connection, policy)
            result = dict(value=value)
        except Exception as error:
            result = dict(error=dict(message=getattr(error, 'message', str(error)), code=getattr(error, 'code', None)))
        finally: await store.close()
        rows.append(dict(mode=mode, result=result, events=events))
    from itertools import permutations
    for headers in ({'x-api-key': 'a', 'Authorization': 'b', '_': 'c'}, {'雪': 'a', 'a': 'b', 'Z': 'c'}):
        for entries in permutations(headers.items()):
            rows.append(dict(headers=[list(row) for row in entries], scope=fileScope(dict(baseURL='https://example.test/anthropic/', headers=dict(entries)))))
    rows.extend(await cancellation_cases())
    return rows


async def cancellation_cases():
    from dsh.core.abort import AbortController
    from dsh.cordis.errors import ThrownValueError
    from dsh.llm.deepseek_file_store_current import DeepSeekFileStore
    rows = []
    for mode in ('one-cancel', 'all-cancel', 'non-error-upload'):
        entered = asyncio.Event(); gate = asyncio.Event(); signals = []
        async def get(*_): return None
        async def commit(record, *_): return dict(record=record, accepted=True)
        async def upload(**input):
            signals.append(input['signal']); entered.set(); await gate.wait()
            if mode == 'non-error-upload': raise ThrownValueError(None)
            input['signal'].throw_if_aborted()
            return dict(id='uploaded', bytes=3, createdAt=1, expiresAt=3601)
        store = DeepSeekFileStore(index=SimpleNamespace(get=get, commit=commit), now=lambda: 1000,
            client_factory=lambda _: SimpleNamespace(upload=upload))
        connection = dict(baseURL='https://a/anthropic', headers={})
        version = dict(attachment=dict(attachmentId='sha256:'+'a'*64), variantId='sha256:'+'b'*64, bytes=3, data=b'abc', mediaType='image/png')
        policy = dict(expiresAfterSeconds=3600, refreshMarginSeconds=1, quotaCleanupBatch=1)
        one = AbortController(); two = AbortController()
        first = store.ensureUploaded(version, connection, policy, one.signal)
        second = store.ensureUploaded(version, connection, policy, two.signal)
        await entered.wait()
        if mode != 'non-error-upload': one.abort(RuntimeError('first'))
        if mode == 'all-cancel': two.abort(None)
        gate.set(); outcomes = []
        for waiter in (first, second):
            try: outcomes.append(dict(value=(await waiter)['record']['fileId']))
            except Exception as error:
                outcomes.append(dict(error=getattr(error, 'message', str(error)), causeNull=hasattr(error, 'cause') and error.cause is None))
        await store.close()
        rows.append(dict(mode=mode, outcomes=outcomes, uploads=len(signals), transportAborted=signals[0].aborted,
                         listeners=[len(one.signal._listeners), len(two.signal._listeners)]))
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_file_store.mts', 'Current upload store: quota pagination, commit losers, expiry conversion and header-scoped namespaces.',
               [Path(__file__).resolve(), ROOT/'dsh/llm/deepseek_file_store_current.py'], prepare=prepare)
