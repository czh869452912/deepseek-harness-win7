"""Actual browser carrier boundaries, independently of Office collaborators."""
import asyncio
import os
import threading
import time
from pathlib import Path

import pytest

from dsh.core.abort import AbortController
from dsh.office.browser_carrier import BrowserCarrier
from dsh.office.errors import OfficeKitError


@pytest.fixture
def carrier(tmp_path):
    executable = os.environ.get('DSH_TEST_OFFICE_BROWSER')
    if not executable:
        pytest.skip('Set DSH_TEST_OFFICE_BROWSER to run the actual Chromium carrier.')
    value = BrowserCarrier(executable, temporary_directory=str(tmp_path))
    yield value
    assert not value.active
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_actual_worker_isolation_bytes_and_exact_assets(carrier, tmp_path):
    # Asset lives outside the profile directory, and is never deleted by carrier cleanup.
    asset = tmp_path.parent / (tmp_path.name + '-asset.bin')
    asset.write_bytes(b'\x00\x7f\xff')
    try:
        value = await carrier.run('''
          Promise.all(['fixture.bin', 'fixture.bin?query', '../fixture.bin', '/fixture.bin'].map(
            async path => {const response = await fetch(path); return {
              status:response.status, bytes:new Uint8Array(await response.arrayBuffer())};}
          )).then(results => self.postMessage({isolated:crossOriginIsolated, results}));
        ''', {'fixture.bin': asset}, timeout=15)
        assert value['isolated'] is True
        assert value['results'][0] == dict(status=200, bytes=b'\x00\x7f\xff')
        assert [row['status'] for row in value['results'][1:]] == [404, 404, 404]
        assert asset.read_bytes() == b'\x00\x7f\xff'
    finally:
        asset.unlink()


@pytest.mark.asyncio
async def test_actual_worker_error(carrier):
    with pytest.raises(OfficeKitError, match='actual worker failure') as caught:
        await carrier.run("throw Error('actual worker failure')", {}, timeout=15)
    assert caught.value.code == 'failed'


@pytest.mark.asyncio
async def test_actual_unhandled_rejection_does_not_wait_for_deadline(carrier):
    with pytest.raises(OfficeKitError, match='async worker failure') as caught:
        await carrier.run("Promise.reject(Error('async worker failure'))", {}, timeout=15)
    assert caught.value.code == 'failed'


@pytest.mark.asyncio
async def test_actual_result_limit_before_body_read(carrier):
    with pytest.raises(ValueError, match='byte limit'):
        await carrier.run("self.postMessage('x'.repeat(10000))", {}, timeout=15, max_result_bytes=1024)


@pytest.mark.asyncio
async def test_actual_result_framing(carrier):
    with pytest.raises(ValueError, match='envelope'):
        await carrier.run("fetch('result',{method:'POST',body:JSON.stringify({unknown:1})})", {}, timeout=15)


@pytest.mark.asyncio
async def test_actual_worker_deadline_joins_process_range(carrier):
    with pytest.raises(OfficeKitError) as caught:
        await carrier.run('setInterval(()=>{},1000)', {}, timeout=.5)
    assert caught.value.code == 'timeout'


@pytest.mark.asyncio
async def test_actual_abort_preserves_reason_and_joins_range(carrier):
    controller = AbortController()
    reason = RuntimeError('exact abort reason')
    operation = asyncio.create_task(carrier.run('setInterval(()=>{},1000)', {}, timeout=15, signal=controller.signal))
    await asyncio.sleep(.5)
    controller.abort(reason)
    with pytest.raises(RuntimeError) as caught:
        await operation
    assert caught.value is reason
    assert not controller.signal._listeners


@pytest.mark.asyncio
async def test_actual_task_cancel_joins_range(carrier):
    operation = asyncio.create_task(carrier.run('setInterval(()=>{},1000)', {}, timeout=15))
    await asyncio.sleep(.5)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation


@pytest.mark.asyncio
async def test_repeated_cancel_does_not_interrupt_profile_cleanup(carrier, monkeypatch):
    from dsh.office import browser_carrier
    original = browser_carrier._remove_tree
    entered = threading.Event()
    def delayed_remove(path):
        entered.set()
        time.sleep(.15)
        original(path)
    monkeypatch.setattr(browser_carrier, '_remove_tree', delayed_remove)
    operation = asyncio.create_task(carrier.run('setInterval(()=>{},1000)', {}, timeout=15))
    await asyncio.sleep(.5)
    operation.cancel()
    while not entered.is_set():
        await asyncio.sleep(.01)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation


@pytest.mark.asyncio
async def test_actual_close_joins_concurrent_ranges_and_rejects_reuse(carrier):
    operations = [asyncio.create_task(carrier.run('setInterval(()=>{},1000)', {}, timeout=15)) for _ in range(2)]
    await asyncio.sleep(.5)
    await asyncio.gather(carrier.close(), carrier.close())
    assert all(isinstance(value, asyncio.CancelledError) for value in
               await asyncio.gather(*operations, return_exceptions=True))
    with pytest.raises(OfficeKitError, match='closed'):
        await carrier.run('self.postMessage(1)', {})


@pytest.mark.asyncio
async def test_preaborted_does_not_launch(carrier):
    controller = AbortController()
    reason = RuntimeError('already aborted')
    controller.abort(reason)
    with pytest.raises(RuntimeError) as caught:
        await carrier.run('', {}, signal=controller.signal)
    assert caught.value is reason


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['../file', 'nested/file', 'file?x', 'file#x', 'result', 'operation.js'])
async def test_invalid_route_never_launches(carrier, route):
    with pytest.raises(ValueError, match='route'):
        await carrier.run('', {route: Path('unused')})
