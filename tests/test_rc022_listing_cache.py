import asyncio
import json
import time

import pytest

from dsh.core.abort import AbortController
from dsh.core.timeout import timeout_of
from dsh.llm.model_listing_cache import LISTING_TIMEOUT, ModelListingCache, resolveListingTiming
from scripts import rc022_listing_cache_probe as corpus


@pytest.mark.asyncio
async def test_cache_generation_retention_and_owned_load_transition_corpus(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'listing-cache-observations.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    by_name = {row['name']: row for row in rows}
    assert len(rows) == 16
    assert len(by_name['shared-load']['loads']) == 1
    assert not by_name['abandoned']['loads'][0]['aborted']
    assert len(by_name['one-warning']['warn']) == 1
    assert by_name['no-change-notification']['changed'] == 1
    assert by_name['badge-change']['changed'] == 2
    assert by_name['late-old-ignored']['current']['listing'] is None
    assert by_name['new-generation-committed']['current']['listing']['entries'][0]['id'] == 'b'
    assert not by_name['dispose-waits']['disposalDone']
    assert by_name['closed']['disposalDone'] and by_name['closed']['current']['listing'] is None


@pytest.mark.parametrize('options', [dict(modelsTimeoutMs=0), dict(modelsTimeoutMs=float('inf')),
    dict(modelsTimeoutMs=2147483648), dict(modelsMaxAgeMs=-1), dict(modelsMaxAgeMs=.5), dict(modelsMaxAgeMs=9007199254740992), dict(modelsMaxAgeMs=True)])
def test_timing_rejects_values_outside_source_bounds(options):
    with pytest.raises(ValueError): resolveListingTiming(options, 'provider')


@pytest.mark.asyncio
async def test_deadline_and_caller_task_cancellation_do_not_cancel_shared_load():
    loads, changed = [], []
    started = asyncio.Event()
    def load(url, token, signal):
        future = asyncio.get_running_loop().create_future()
        def abort(*_):
            if not future.done(): future.set_exception(signal.reason)
        detach = signal.add_listener('abort', abort)
        future.add_done_callback(lambda _: detach())
        loads.append((signal, future))
        started.set()
        return future
    settings = dict(url='https://api.example/models', timeoutMs=30, maxAgeMs=0)
    cache = ModelListingCache(dict(settings=lambda: settings, credential=lambda _: 'token', load=load,
        now=lambda: time.monotonic()*1000, info=lambda _: None, warn=lambda _: None, changed=lambda: changed.append(True)))
    try:
        first = asyncio.create_task(cache.view(settings))
        await asyncio.wait_for(started.wait(), 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError): await first
        assert not loads[0][0].aborted
        result = await asyncio.wait_for(cache.view(settings), 1)
        assert result == dict(authenticated=True, listing=None)
        assert timeout_of(loads[0][0], LISTING_TIMEOUT).timeoutMs == 30
        assert not cache.pending and cache.timer is None and changed == []
    finally:
        await cache.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('reject', [False, True])
async def test_disposal_owns_automatic_credential_lookup(reject):
    waiting, entered = asyncio.get_running_loop().create_future(), asyncio.Event()
    calls, changed, warnings = [], [], []
    def credential(_):
        calls.append(True)
        if len(calls) == 1:
            return 'token'
        entered.set()
        return waiting
    settings = dict(url='https://api.example/models', timeoutMs=1000, maxAgeMs=10)
    cache = ModelListingCache(dict(settings=lambda: settings, credential=credential,
        load=lambda *_: dict(entries=[dict(id='a')], skipped=0), now=lambda: time.monotonic()*1000,
        info=lambda _: None, warn=warnings.append, changed=lambda: changed.append(True)))
    disposal = None
    try:
        await cache.view(settings)
        await asyncio.wait_for(entered.wait(), 1)
        disposal = asyncio.create_task(cache.dispose())
        await asyncio.sleep(0)
        assert not disposal.done()
        if reject:
            waiting.set_exception(RuntimeError('offline'))
        else:
            waiting.set_result('token')
        await asyncio.wait_for(disposal, 1)
        assert len(calls) == 2 and changed == [True] and not warnings
        assert not cache.pending and cache.timer is None
    finally:
        if not waiting.done(): waiting.set_result(None)
        await cache.dispose()
        if disposal is not None: await disposal


@pytest.mark.asyncio
async def test_actual_timer_uses_latest_settings_and_rotated_credential():
    state = dict(token='a', enabled=True)
    observed, changed = [], asyncio.Queue()
    settings = dict(url='https://api.example/models', timeoutMs=1000, maxAgeMs=10)
    def load(url, token, signal):
        observed.append(token)
        return dict(entries=[dict(id=token)], skipped=0)
    cache = ModelListingCache(dict(settings=lambda: settings if state['enabled'] else None,
        credential=lambda _: state['token'], load=load, now=lambda: time.monotonic()*1000,
        info=lambda _: None, warn=lambda _: None, changed=lambda: changed.put_nowait(cache.current())))
    try:
        await cache.view(settings)
        assert (await changed.get())['listing']['entries'][0]['id'] == 'a'
        state['token'] = 'b'
        assert (await asyncio.wait_for(changed.get(), 1))['listing']['entries'][0]['id'] == 'b'
        state['token'] = None
        assert (await asyncio.wait_for(changed.get(), 1)) == dict(authenticated=False, listing=None)
        state['enabled'] = False
        assert (await asyncio.wait_for(changed.get(), 1))['listing'] is None
        assert cache.timer is None and observed == ['a', 'b']
    finally:
        await cache.dispose()
    assert not cache.pending and cache.timer is None
