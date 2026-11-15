import asyncio

import pytest

from dsh.jobs.pump import start_pump
from dsh.jobs.ring import OutputRing
from scripts.rc022_job_output_probe import observe


@pytest.mark.asyncio
async def test_ring_utf8_offsets_and_final_ordered_pump_drains():
    rows=await observe()
    assert len(rows)==10
    for row in rows[-2:]:
        assert [item['append'] for item in row['trace'] if 'append' in item]==['head-stdout','head-stderr','tail-stdout','tail-stderr']
        assert row['trace'][-2]==dict(spill=1,path=None)
        assert row['trace'][-1]['options']==dict(channel='stderr',gapBefore=True)
    ring=OutputRing();ring.append('你好',dict(channel='stdout'),4)
    assert ring.readFrom(0)==dict(chunks=[dict(at=3,text='好',channel='stdout',gapBefore=True)],next=6,lossy=True)
    ring.readFrom(0)['chunks'][0]['text']='mutated'
    assert ring.readFrom(4)['chunks'][0]['text']=='好'


@pytest.mark.asyncio
async def test_pump_waiter_cancel_does_not_cancel_owned_final_drain():
    producer=asyncio.get_running_loop().create_future();reads=[]
    def read(offset):reads.append(offset);return dict(text='x',nextOffset=offset+1,lossy=False)
    pump=start_pump([dict(read=read)],dict(append=lambda *_:None,spill=lambda *_:None),10000,producer)
    async def wait():await pump.done
    waiter=asyncio.create_task(wait());await asyncio.sleep(0);waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    producer.set_result(None);await asyncio.wait_for(pump.done,1)
    assert reads==[0,1]


@pytest.mark.asyncio
async def test_pump_source_failure_stops_polling_and_observes_later_rejection():
    producer=asyncio.get_running_loop().create_future();reads=[]
    def read(offset):reads.append(offset);raise RuntimeError('source failed')
    pump=start_pump([dict(read=read)],dict(append=lambda *_:None,spill=lambda *_:None),1,producer)
    with pytest.raises(RuntimeError,match='source failed'):await pump.done
    producer.set_exception(RuntimeError('late producer rejection'));await asyncio.sleep(0)
    assert reads==[0] and producer._log_traceback is False


@pytest.mark.parametrize('interval',[0,-1,False,None,float('inf')])
def test_invalid_pump_interval_allocates_no_tasks(interval):
    with pytest.raises(ValueError,match='positive finite'):start_pump([],None,interval,None)
