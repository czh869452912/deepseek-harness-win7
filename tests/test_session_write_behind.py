import asyncio
import copy
import heapq
import pytest
from dsh.session.write_behind import SessionWriteBehind

class Clock:
    def __init__(self):
        self.now = 0
        self.queue = []
        self.serial = 0
    def call_later(self, delay, callback):
        self.serial += 1
        handle = asyncio.Handle(callback, (), asyncio.get_running_loop())
        heapq.heappush(self.queue, (self.now + round(delay * 1000), self.serial, handle))
        return handle
    def create_task(self, coro):
        return asyncio.create_task(coro)
    def create_future(self):
        return asyncio.get_running_loop().create_future()
    async def advance(self, milliseconds):
        end = self.now + milliseconds
        while self.queue and self.queue[0][0] <= end:
            self.now, _, handle = heapq.heappop(self.queue)
            if not handle.cancelled():
                handle._run()
            await settle()
        self.now = end
        await settle()

async def settle():
    for _ in range(12):
        await asyncio.sleep(0)

def event(seq):
    return dict(type='turn/start', seq=seq, time=seq, data=dict(turn=seq+1))

def controller(write, report=None):
    clock = Clock()
    return SessionWriteBehind(write, report or (lambda error: None), loop=clock), clock

@pytest.mark.asyncio
async def test_fixed_window_copies_and_batches_twenty_events():
    batches = []
    writes, clock = controller(lambda batch: batches.append(copy.deepcopy(batch)))
    first = event(0)
    writes.enqueue(first)
    first['data']['turn'] = 99
    for seq in range(1, 20):
        await clock.advance(10)
        writes.enqueue(event(seq))
    assert batches == []
    await clock.advance(10)
    assert batches == [[event(seq) for seq in range(20)]]
    assert not writes.has_work

@pytest.mark.asyncio
async def test_concurrent_flush_joins_barrier_and_drains_new_tail():
    gate = asyncio.Event()
    batches = []
    async def write(batch):
        batches.append([e['seq'] for e in batch])
        if len(batches) == 1:
            await gate.wait()
    writes, clock = controller(write)
    writes.enqueue(event(0))
    first = writes.flush()
    assert writes.flush() is first
    await settle()
    writes.enqueue(event(1))
    gate.set()
    await first
    assert batches == [[0], [1]]
    assert not writes.has_work
    await clock.advance(1000)
    assert batches == [[0], [1]]

@pytest.mark.asyncio
async def test_quiescent_flush_does_not_capture_later_enqueue():
    batches=[]
    writes, clock = controller(lambda batch: batches.append(batch))
    barrier=writes.flush()
    writes.enqueue(event(0))
    await barrier
    assert batches == []
    await clock.advance(200)
    assert len(batches) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('expired', [True, False])
async def test_tail_deadline_during_active_write(expired):
    gate=asyncio.Event()
    batches=[]
    async def write(batch):
        batches.append([e['seq'] for e in batch])
        if len(batches)==1: await gate.wait()
    writes, clock=controller(write)
    writes.enqueue(event(0))
    await clock.advance(200)
    writes.enqueue(event(1))
    await clock.advance(200 if expired else 50)
    gate.set()
    await settle()
    assert batches == ([[0],[1]] if expired else [[0]])
    if not expired:
        await clock.advance(149)
        assert batches == [[0]]
        await clock.advance(1)
        assert batches == [[0],[1]]
    await writes.flush()

@pytest.mark.asyncio
async def test_background_failure_pauses_and_new_work_retries_in_order():
    batches=[]; errors=[]
    def write(batch):
        batches.append([e['seq'] for e in batch])
        if len(batches)==1: raise OSError('unavailable')
    writes, clock=controller(write, errors.append)
    writes.enqueue(event(0))
    await clock.advance(200)
    await clock.advance(1000)
    assert batches == [[0]] and len(errors)==1 and writes.has_work
    writes.enqueue(event(1))
    await clock.advance(199)
    assert batches == [[0]]
    await clock.advance(1)
    assert batches == [[0],[0,1]]
    assert not writes.has_work

@pytest.mark.asyncio
async def test_overlapping_background_failure_retries_inside_flush():
    gate=asyncio.Event(); batches=[]; errors=[]
    async def write(batch):
        batches.append([e['seq'] for e in batch])
        if len(batches)==1:
            await gate.wait()
            raise OSError('transient')
    writes, clock=controller(write, errors.append)
    writes.enqueue(event(0)); await clock.advance(200)
    first=writes.flush()
    assert writes.flush() is first
    gate.set(); await first
    assert batches == [[0],[0]] and len(errors)==1
    assert not writes.has_work

@pytest.mark.asyncio
async def test_barrier_failure_retains_large_batch_without_detached_reporting():
    sizes=[]; errors=[]
    def write(batch):
        sizes.append(len(batch))
        if len(sizes)==1: raise OSError('durability')
    writes, clock=controller(write, errors.append)
    for seq in range(150000): writes.enqueue(event(seq))
    with pytest.raises(OSError): await writes.flush()
    assert not errors and writes.has_work
    await writes.flush()
    assert sizes==[150000,150000] and not writes.has_work
