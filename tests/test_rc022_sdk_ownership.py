import asyncio

import pytest

from dsh.sdk.client import create_process_deepseek_harness
from dsh.sdk.errors import RequestTimeoutError
from test_rc022_sdk_process import runtime, assert_reaped, until


@pytest.mark.asyncio
@pytest.mark.parametrize('timeout', [False, True])
async def test_close_observer_cannot_interrupt_actual_owned_child_reaping(tmp_path,timeout):
    harness=create_process_deepseek_harness(runtime(tmp_path,IGNORE_SHUTDOWN='1',IGNORE_EOF='1'),dict(cwd=str(tmp_path)))
    try:
        await harness.start()
        shared=harness.close()
        assert shared is harness.close()
        async def wait():return await shared
        one,two=asyncio.create_task(wait()),asyncio.create_task(wait())
        await asyncio.sleep(0)
        if timeout:
            with pytest.raises(asyncio.TimeoutError):await asyncio.wait_for(one,.005)
        else:
            one.cancel()
            with pytest.raises(asyncio.CancelledError):await one
        assert not shared.done() and harness.client.child.poll() is None
        await asyncio.wait_for(two,3)
        assert_reaped(harness.client)
    finally:await harness.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('timeout', [False, True])
async def test_start_observer_leaves_owner_to_settle_failure_and_reap_before_replacement(tmp_path,timeout):
    marker=tmp_path/'ready'
    harness=create_process_deepseek_harness(runtime(tmp_path,HANG_INIT='1',RECORD_INIT=str(marker)),dict(cwd=str(tmp_path)))
    original=harness.client
    try:
        shared=harness.start()
        assert shared is harness.start()
        async def wait():return await shared
        one,two=asyncio.create_task(wait()),asyncio.create_task(wait())
        await until(marker.exists)
        if timeout:
            with pytest.raises(asyncio.TimeoutError):await asyncio.wait_for(one,.005)
        else:
            one.cancel()
            with pytest.raises(asyncio.CancelledError):await one
        assert not shared.done() and harness.client is original and original.child.poll() is None
        with pytest.raises(RequestTimeoutError):await asyncio.wait_for(two,3)
        assert_reaped(original)
        assert harness.client is not original and harness.client.child is None
    finally:await harness.close()
