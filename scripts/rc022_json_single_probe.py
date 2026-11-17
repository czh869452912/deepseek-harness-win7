"""Current single JSON medium, compatible reads and durable write boundaries."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

FILES=None

def cases():
    base=dict(unit=dict(name='shape',version=1),global_=None,tables=dict(t=dict(a=1,b=2,c=3)))
    base['global']=base.pop('global_')
    rows=[]
    for version in [0,1,2,3,True,'1',1.5,None]:
        rows.append(dict(op='parse',document=dict(base,unit=dict(name='shape',version=version))))
    for tables in [{},dict(t={}),dict(t=None),dict(t=[]),dict(t='bad'),[],None]:
        rows.append(dict(op='parse',document=dict(base,tables=tables)))
    rows.extend([dict(op='parse',document=dict(base,unit=dict(name='foreign',version=1))),dict(op='parse',text='{bad')])
    for action in ['read','put','deleteMissing','deleteBatch','global','reopen','drain','concurrentOpen']:
        rows.append(dict(op=action,document=base))
    return rows

def prepare(output):
    global FILES
    FILES=output/'files';FILES.mkdir()
    path=output/'inputs.json';path.write_text(json.dumps(dict(cases=cases(),files=str(FILES))),encoding='utf-8');return [path]

async def observe(files=None):
    import asyncio
    from dsh.storage.storage_json import JsonStorageBackend,parse
    from dsh.storage.backend import KvUnitDescriptor
    files=Path(files or FILES);files.mkdir(exist_ok=True,parents=True);rows=[]
    desc=KvUnitDescriptor('shape',2,['t'],True,compatible_versions=[1])
    for index,case in enumerate(cases()):
        try:
            if case['op']=='parse':value=parse(case.get('text',json.dumps(case.get('document'))),desc)
            else:
                folder=files/('native-'+str(index));folder.mkdir();path=folder/'shape.json'
                before=json.dumps(case['document']);path.write_text(before,encoding='utf-8');backend=JsonStorageBackend(str(folder))
                unit=await backend.kv.open(desc);value={}
                try:
                    op=case['op']
                    if op=='put':await unit.putRecord('t','d',4)
                    elif op=='deleteMissing':await unit.deleteRecords('t',['missing','missing'])
                    elif op=='deleteBatch':await unit.deleteRecords('t',['a','c','missing','a'])
                    elif op=='global':await unit.setGlobal(dict(saved=True))
                    elif op=='reopen':
                        await unit.close();unit=await backend.kv.open(desc)
                    elif op=='drain':
                        write=asyncio.create_task(unit.putRecord('t','d',4));await asyncio.sleep(0)
                        await unit.close();await write
                    elif op=='concurrentOpen':
                        await unit.close()
                        first=asyncio.create_task(backend.kv.open(desc));second=asyncio.create_task(backend.kv.open(desc))
                        outcome=await asyncio.gather(first,second,return_exceptions=True)
                        unit=outcome[0];value['secondRejected']=isinstance(outcome[1],Exception)
                    value.update(snapshot=None if op=='drain' else await unit.loadAll(),unchanged=path.read_text(encoding='utf-8')==before,disk=json.loads(path.read_text(encoding='utf-8')))
                finally:await backend.close()
            rows.append(dict(op=case['op'],value=value))
        except Exception as error:rows.append(dict(op=case['op'],error=dict(code=getattr(error,'code',None),message=getattr(error,'message',str(error)))))
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_json_single.mts',prepare=prepare,scope='Single JSON parse, compatible v1 reads/current v2 publishes, no-op deletes, batch deletes, snapshots and handle lifecycle.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/storage/storage_json.py',ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/storage/storage-json/src/single-unit.ts',ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/storage/storage-json/src/format.ts'])
