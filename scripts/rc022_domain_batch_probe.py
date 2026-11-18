"""Atomic domain batches, observer snapshots and unknown-state quarantine."""
import asyncio
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

def cases():
    return [dict(keys=keys,failure=failure,throwObserver=throw) for keys in [[],['missing'],['a','c','a','missing']]
        for failure,throw in [(None,False),(None,True),('normal',False),('unknown-state',False)]]+[
        dict(keys=['queued','a'],failure=failure,throwObserver=False,queued=True) for failure in [None,'normal','unknown-state']]

def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]

async def observe():
    from dsh.storage.domain_impl import DomainImpl
    from dsh.storage.domain_spec import define_domain,domain_table,DomainGlobalSpec
    from dsh.storage.error import StorageError
    rows=[]
    for case in cases():
        calls=[];events=[];warnings=[];medium=dict(a=1,b=2,c=3);closed=[];domain=None
        failure=StorageError('unknown-state' if case['failure']=='unknown-state' else 'malformed-medium','refused')
        gate=asyncio.Event();entered=asyncio.Event()
        class Unit:
            async def put_record(self,table,key,value):calls.append(['put',key,value]);medium[key]=value
            async def delete_records(self,table,keys):
                calls.append(['batch',list(keys)]);entered.set()
                if case.get('queued'):await gate.wait()
                if case['failure']=='normal':raise failure
                if case['failure']=='unknown-state':medium.pop(keys[0],None);raise failure
                for key in keys:medium.pop(key,None)
            async def set_global(self,value):calls.append(['global',value])
            async def close(self):closed.append('unit')
        class Logger:
            def warn(self,message):warnings.append(True)
        class Context:
            logger=Logger()
            def emit(self,event,change):
                events.append(dict(key=change.key,operation=change.operation,view=dict(domain.table('t').entries())))
                if case['throwObserver']:raise ValueError('observer failed')
        spec=define_domain(name='shape',version=1,tables=dict(t=domain_table(lambda value:value)),global_spec=DomainGlobalSpec(int,0))
        domain=DomainImpl(Context(),spec,Unit(),dict(t=dict(medium)),0,lambda:closed.append('domain'));table=domain.table('t')
        async def result(awaitable):
            try:return dict(value=await awaitable)
            except Exception as error:return dict(error=dict(code=getattr(error,'code',None),same=error is failure))
        if case.get('queued'):
            await table.put('queued',4)
            deletion=asyncio.create_task(result(table.deleteMany(case['keys'])));await entered.wait()
            after=asyncio.create_task(result(table.put('after',5)));await asyncio.sleep(0);gate.set()
            deleted,following=await asyncio.gather(deletion,after)
        else:
            deleted=await result(table.deleteMany(case['keys']));following=await result(table.put('after',5))
        reads={}
        for name,read in [('get',lambda:table.get('b')),('entries',lambda:dict(table.entries())),('keys',lambda:table.keys()),('size',lambda:table.size),('global',lambda:domain.global_.get())]:
            try:reads[name]=dict(value=read())
            except Exception as error:reads[name]=dict(error=dict(code=getattr(error,'code',None),same=error is failure))
        await domain.close();await domain.close()
        try:table.get('b')
        except Exception as error:after_close=getattr(error,'code',None)
        rows.append(dict(case=case,deleted=deleted,following=following,calls=calls,events=events,warnings=len(warnings),reads=reads,medium=medium,closed=closed,afterClose=after_close))
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_domain_batch.mts',prepare=prepare,scope='One backend delete per domain FIFO batch; complete observer snapshots, ordinary rejection progress, unknown-state identity quarantine including already-queued writes, close precedence.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/storage/domain_impl.py',ROOT/'dsh/storage/backend.py',ROOT/'reference/packages/storage/storage-domain/src/domain.ts'])
