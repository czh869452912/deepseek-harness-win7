"""Job output ring and pump contracts before registry integration."""
import asyncio
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.jobs.ring import OutputRing
from dsh.jobs.pump import start_pump


async def observe():
    rows=[]
    for cap in [0,1,2,3,4,7,16,64]:
        ring=OutputRing();snapshots=[]
        for text,options in [('',None),('abc',None),('你好',dict(channel='stdout')),('😀z',dict(channel='stderr',gapBefore=True)),('x'*90,None),('e\u0301',dict(channel='meta')),('\ud800',None)]:
            changed=ring.append(text,options,cap)
            snapshots.append(dict(changed=changed,retained=ring.retainedBytes,total=ring.total,earliest=ring.earliest,reads=[ring.readFrom(offset) for offset in [0,1,4,ring.total-1,ring.total,ring.total+1]]))
        read=ring.readFrom(0)
        if read['chunks']:read['chunks'][0]['text']='mutated'
        ring.trim(1);snapshots.append(dict(read=ring.readFrom(0)))
        rows.append(dict(name='ring',cap=cap,snapshots=snapshots))
    for rejection in [False,True]:
        trace=[];until=asyncio.get_running_loop().create_future();state=dict(final=False)
        def source(channel):
            def read(cursor):
                trace.append(dict(read=channel,cursor=cursor))
                return dict(text=('tail-'+channel) if state['final'] else ('head-'+channel),nextOffset=20 if state['final'] else 10,lossy=state['final'],**(dict(spillPath='spill-'+channel) if not state['final'] else {}))
            return dict(channel=channel,read=read)
        sink=dict(append=lambda text,options=None:trace.append(dict(append=text,options=options)),spill=lambda index,path:trace.append(dict(spill=index,path=path)))
        pump=start_pump([source('stdout'),source('stderr')],sink,10000,until)
        state['final']=True
        if rejection:until.set_exception(RuntimeError('producer rejected'))
        else:until.set_result(None)
        await pump.done
        rows.append(dict(name='pump',rejection=rejection,trace=trace))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_job_output.mts','Actual ring operations with byte offsets, multi-chunk eviction, codepoint-safe truncation, unpaired surrogate replacement and independent reads. Actual pump ordered source drain, spill withdrawal, final drain on resolve/reject and large pending timer cancellation. Registry/model cursor integration remains separate.',[Path(__file__).resolve(),ROOT/'dsh/jobs/ring.py',ROOT/'dsh/jobs/pump.py'])
