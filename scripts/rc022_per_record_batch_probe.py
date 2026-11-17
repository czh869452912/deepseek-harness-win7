"""Per-record JSON deletion, legacy bootstrap and durable empty-tree identity."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from dsh.storage.storage_json import JsonStorageBackend
    from dsh.storage.backend import KvUnitDescriptor
    rows=[]
    for bootstrap in [False,True]:
        root=WORKSPACE/('native-'+str(bootstrap));root.mkdir();descriptor=KvUnitDescriptor('batch',2,['t'],True,layout='per-record',compatible_versions=[1])
        legacy=json.dumps(dict(unit=dict(name='batch',version=1),tables=dict(t=dict(a=dict(n=1),b=dict(n=2)))),separators=(',',':'))
        if bootstrap:(root/'batch.json').write_text(legacy,encoding='utf-8')
        backend=JsonStorageBackend(str(root));unit=await backend.kv.open(descriptor)
        try:
            rows.append(dict(bootstrap=bootstrap,phase='opened',state=await unit.load_all()))
            if not bootstrap:
                await unit.put_record('t','a',dict(n=1));await unit.put_record('t','b',dict(n=2))
            await unit.delete_records('t',['missing','a','a']);rows.append(dict(bootstrap=bootstrap,phase='first',state=await unit.load_all()))
            await unit.deleteRecord('t','b');await unit.delete_records('t',[])
            rows.append(dict(bootstrap=bootstrap,phase='empty',state=await unit.load_all(),tableExists=(root/'batch/t').is_dir(),files=sorted(path.name for path in (root/'batch/t').iterdir())))
            await unit.close();unit=await backend.kv.open(descriptor)
            rows.append(dict(bootstrap=bootstrap,phase='reopened',state=await unit.load_all(),legacyUnchanged=not bootstrap or (root/'batch.json').read_text(encoding='utf-8')==legacy))
            await unit.put_record('t','receipt',dict(done=True));saved=(root/'batch/t/receipt.json').read_bytes();backup=await unit.backupRecord('t','receipt')
            rows.append(dict(bootstrap=bootstrap,phase='backup',state=await unit.load_all(),sameBytes=Path(backup).read_bytes()==saved,backupIgnored=not backup.endswith('.json')))
        finally:await unit.close();await backend.close()
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_per_record_batch.mts','Actual current per-record JSON files: accepted-version legacy bootstrap, deduplicated/missing/empty batches, emptied declared tree suppresses stale legacy resurrection across reopen, unchanged legacy bytes and byte-preserving backup excluded from readable documents.',[Path(__file__).resolve(),ROOT/'dsh/storage/per_record_json.py'],prepare=prepare)
