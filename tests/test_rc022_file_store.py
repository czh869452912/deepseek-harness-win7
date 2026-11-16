import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.cordis.errors import ThrownValueError
from dsh.llm.deepseek_file_store_current import DeepSeekFileStore
from scripts import rc022_file_store_probe as corpus

CONNECTION = dict(baseURL='https://example.test/anthropic', headers={'x-api-key': 'secret'})
POLICY = dict(expiresAfterSeconds=3600, refreshMarginSeconds=10, quotaCleanupBatch=2)
VERSION = dict(attachment=dict(attachmentId='sha256:'+'a'*64), variantId='sha256:'+'b'*64,
               bytes=3, data=b'abc', mediaType='image/png')


def controlled_store():
    started = []; gates = []; signals = []
    async def get(*_): return None
    async def commit(record, *_): return dict(record=record, accepted=True)
    async def upload(**input):
        gate = asyncio.Event(); gates.append(gate); signals.append(input['signal']); started.append(input)
        await gate.wait()
        input['signal'].throw_if_aborted()
        return dict(id='file-'+str(len(started)), bytes=3, createdAt=1, expiresAt=3601)
    store = DeepSeekFileStore(index=SimpleNamespace(get=get, commit=commit), now=lambda: 1000,
        client_factory=lambda _: SimpleNamespace(upload=upload))
    return store, started, gates, signals


async def until(predicate):
    for _ in range(500):
        if predicate(): return
        await asyncio.sleep(.002)
    assert predicate(), 'controlled upload did not reach its boundary'


@pytest.mark.asyncio
async def test_current_store_policy_corpus(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'file-store-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == 29
    reclaim = next(row for row in rows if row.get('mode') == 'reclaim')
    assert [event['delete'] for event in reclaim['events'] if 'delete' in event] == ['oldest', 'middle']
    assert len([event for event in reclaim['events'] if 'list' in event]) == 2
    namespaces = [row['scope'] for row in rows if 'headers' in row]
    assert len(set(namespaces[:6])) == len(set(namespaces[6:])) == 1


@pytest.mark.asyncio
async def test_one_cancelled_waiter_preserves_shared_upload_and_other_reason_identity():
    store, started, gates, signals = controlled_store()
    one = AbortController(); two = AbortController(); reason = RuntimeError('one stopped')
    first = store.ensureUploaded(VERSION, CONNECTION, POLICY, one.signal)
    second = store.ensureUploaded(VERSION, CONNECTION, POLICY, two.signal)
    try:
        await until(lambda: bool(started))
        one.abort(reason)
        with pytest.raises(RuntimeError) as caught: await first
        assert caught.value is reason and not signals[0].aborted
        gates[0].set(); result = await second
        assert result['uploaded'] and len(started) == 1
        await until(lambda: not store.inflight)
        assert not one.signal._listeners and not two.signal._listeners
    finally:
        for gate in gates: gate.set()
        await store.close()


@pytest.mark.asyncio
async def test_last_waiter_abort_starts_new_generation_and_old_completion_preserves_it():
    store, started, gates, signals = controlled_store()
    controller = AbortController()
    old = store.ensureUploaded(VERSION, CONNECTION, POLICY, controller.signal)
    try:
        await until(lambda: len(started) == 1)
        controller.abort(None)
        with pytest.raises(RuntimeError, match='non-Error reason') as caught: await old
        assert caught.value.cause is None and signals[0].reason is caught.value
        new = store.ensureUploaded(VERSION, CONNECTION, POLICY)
        await until(lambda: len(started) == 2)
        generation = next(iter(store.inflight.values()))
        gates[0].set(); await asyncio.sleep(.01)
        assert next(iter(store.inflight.values())) is generation
        gates[1].set(); assert (await new)['uploaded']
    finally:
        for gate in gates: gate.set()
        await store.close()


@pytest.mark.asyncio
async def test_preaborted_primitive_is_thrown_before_any_upload_or_namespace_work():
    store, started, gates, signals = controlled_store(); controller = AbortController(); controller.abort(False)
    try:
        with pytest.raises(ThrownValueError) as caught:
            store.ensureUploaded(VERSION, {}, POLICY, controller.signal)
        assert caught.value.value is False and not started and not store.inflight
    finally: await store.close()


@pytest.mark.asyncio
async def test_python_waiter_cancellation_aborts_transport_and_close_joins_it():
    store, started, gates, signals = controlled_store()
    waiter = store.ensureUploaded(VERSION, CONNECTION, POLICY)
    try:
        await until(lambda: bool(started)); waiter.cancel()
        await until(lambda: signals[0].aborted)
        gates[0].set(); await store.close()
        assert not store.inflight
    finally:
        for gate in gates: gate.set()
        await store.close()
