"""Current SQLite atomic batch and compatible-version publication."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from dsh.storage.storage_sqlite import SqliteStorageBackend
    from dsh.storage.backend import KvUnitDescriptor
    rows=[]
    for operation in ['put','global','delete','batch','missing','empty','abort','rollback','stamp-failed']:
        backend=SqliteStorageBackend(dict(path=str(WORKSPACE/('native-'+operation+'.db'))));unit=None
        try:
            unit=await backend.kv.open(KvUnitDescriptor('specimen',1,['records'],True))
            for key in ['a','b']:await unit.put_record('records',key,dict(n=key))
            await unit.set_global(dict(old=True));await unit.close()
            unit=await backend.kv.open(KvUnitDescriptor('specimen',2,['records'],True,compatible_versions=[1]))
            rows.append(dict(operation=operation,phase='opened',version=backend.db.execute("SELECT version FROM units WHERE name='specimen'").fetchone()[0],state=await unit.load_all()))
            if operation in ('abort','rollback'):backend.db.execute("CREATE TRIGGER refuse BEFORE DELETE ON u_specimen_records WHEN old.key='b' BEGIN SELECT RAISE("+operation.upper()+", 'blocked'); END")
            if operation=='stamp-failed':backend.db.execute("CREATE TRIGGER refuse BEFORE UPDATE ON units BEGIN SELECT RAISE(ABORT, 'stamp blocked'); END")
            error=None
            try:
                if operation=='put':await unit.put_record('records','c',dict(new=True))
                elif operation=='global':await unit.set_global(dict(new=True))
                elif operation=='delete':await unit.delete_record('records','a')
                elif operation=='missing':await unit.delete_records('records',['missing','missing'])
                elif operation=='empty':await unit.delete_records('records',[])
                else:await unit.delete_records('records',['a','b','a','missing'])
            except Exception as failure:error=str(failure)
            rows.append(dict(operation=operation,phase='mutation',error=error,version=backend.db.execute("SELECT version FROM units WHERE name='specimen'").fetchone()[0],state=await unit.load_all()))
            await unit.close();unit=None;await backend.close()
            backend=SqliteStorageBackend(dict(path=str(WORKSPACE/('native-'+operation+'.db'))));unit=await backend.kv.open(KvUnitDescriptor('specimen',2,['records'],True,compatible_versions=[1]))
            rows.append(dict(operation=operation,phase='reopened',state=await unit.load_all()))
        finally:
            if unit is not None:await unit.close()
            await backend.close()
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sqlite_batch.mts','Actual SQLite files and cold reopen: compatible version read without stamp, first put/global/delete/batch commits version with mutation, deduplicated/missing/empty batch, ABORT and ROLLBACK trigger rollback, version-stamp failure restores data and old stamp.',[Path(__file__).resolve(),ROOT/'dsh/storage/storage_sqlite.py'],prepare=prepare,node_args=['--expose-internals'])
