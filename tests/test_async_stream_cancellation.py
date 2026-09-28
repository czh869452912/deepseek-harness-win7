import asyncio
import pytest
from dsh.llm.stream_bridge import iter_chunks


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
