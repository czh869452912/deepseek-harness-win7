import asyncio
import threading
import pytest
from dsh.llm.stream_bridge import OwnedStream, iter_chunks


@pytest.mark.asyncio
async def test_cancel_idle_async_reader_drains_pending_read_and_closes_source():
    entered, closed, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def source():
        try:
            entered.set()
            await asyncio.Event().wait()
            yield 'unreachable'
        finally:
            await asyncio.sleep(0)
            closed.set()
    async def consume():
        async for _ in iter_chunks(source(), cancelled.is_set):
            pytest.fail('blocked source should not yield')
    task = asyncio.create_task(consume())
    await entered.wait()
    cancelled.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_async_reader_early_close_does_not_request_another_chunk():
    reads, closed = [], []
    async def source():
        try:
            for value in range(3):
                reads.append(value)
                yield value
        finally:
            closed.append(True)
    reader = iter_chunks(source())
    assert await reader.__anext__() == 0
    await reader.aclose()
    assert reads == [0] and closed == [True]


@pytest.mark.asyncio
async def test_sync_reader_wakes_consumer_and_keeps_demand_backpressure():
    reads, closed, workers = [], [], []
    def source(signal):
        workers.append(threading.current_thread())
        try:
            for value in range(2048):
                reads.append(value)
                yield value
        finally:
            closed.append(True)
    reader = iter_chunks(OwnedStream(source))
    try:
        assert await reader.__anext__() == 0
        await asyncio.sleep(.025)
        assert reads == [0]
        # A rapid local response must fit the HTTP deadline rather than spend
        # at least 10 ms polling for each of its 2048 chunks.
        async def rest(): return [item async for item in reader]
        assert await asyncio.wait_for(rest(), 5) == list(range(1, 2048))
    finally:
        await reader.aclose()
    assert closed == [True] and all(not worker.is_alive() for worker in workers)


@pytest.mark.asyncio
async def test_repeated_cancel_drains_blocked_owned_sync_reader():
    started, closed, workers = threading.Event(), [], []
    def source(signal):
        workers.append(threading.current_thread()); started.set()
        try:
            while not signal.aborted: threading.Event().wait(.005)
            if False: yield None
        finally:
            closed.append(True)
    async def consume():
        async for _ in iter_chunks(OwnedStream(source)):
            pytest.fail('cancelled reader must not produce data')
    task = asyncio.create_task(consume())
    while not started.is_set(): await asyncio.sleep(0)
    task.cancel()
    asyncio.get_running_loop().call_later(.001, task.cancel)
    with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task, 2)
    assert closed == [True] and all(not worker.is_alive() for worker in workers)
