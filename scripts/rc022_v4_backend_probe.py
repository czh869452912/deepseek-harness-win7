"""Exercise V4 handles and child-aware historical migration through the backend."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

OUTPUT=None
ACTIONS=['create','v0','v1','v2','v3','child-v4','child-v3','child-invalid','membership-add','membership-remove','child-changed','unrelated-changed']
CASES=[dict(action=action,compression=compression) for compression in ('none','zstd') for action in ACTIONS]


def prepare(output):
    global OUTPUT
    OUTPUT=output;path=output/'input.json';path.write_text(json.dumps(CASES),encoding='utf-8');return [path]


async def observe(workspace):
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistence
    from dsh.session.jsonl_current import generationLogPath
    from dsh.session.jsonl_zstd import compress_frame
    from dsh.core.session.current_session import CurrentSession
    from dsh.compaction.image_offload import imageOffloadProjection
    from dsh.core.session.json import UNDEFINED
    results=[]
    for row in CASES:
        action,compression=row['action'],row['compression'];root=workspace/(compression+'-'+action);root.mkdir(parents=True)
        backend=CurrentJsonlSessionPersistence(str(root),compression,format_version=4)
        header=dict(version=4,id='parent',createdAt=1,isSeeded=False,delegationDepth=0)
        originals={};result=dict(action=action,compression=compression)
        def raw_write(identity,version,events=None,**metadata):
            value=dict(header,id=identity,version=version,**metadata)
            if version<2:value.pop('isSeeded');value['seedLength']=0
            first=(json.dumps(dict(type='session',**value),separators=(',',':'))+'\n').encode('utf-8')
            body=''.join(json.dumps(event,separators=(',',':'))+'\n' for event in (events or [])).encode('utf-8')
            data=first+body if compression=='none' else compress_frame(first)+(compress_frame(body) if body else b'')
            path=Path(generationLogPath(str(root),metadata.get('cwd',UNDEFINED),identity,version,compression))
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);originals[path]=data;return path
        def summarize(snapshot):
            return dict(version=snapshot['header']['version'],status=snapshot.get('formatStatus'),
                location=Path(snapshot['location']['path']).name if 'location' in snapshot else None,
                corpus=len(snapshot['revision'].split(':')[-1])==64)
        child=None
        try:
            if action=='create':
                handle=await backend.create(header);result['pending']=summarize(await backend.stat('parent'))
                user=dict(type='user/message',seq=0,time=1,surfaceOp='append',data=dict(id='image',role='user',source=dict(kind='user'),content=[dict(type='image',attachment={})]))
                image=dict(type='image/offload',seq=1,time=1,data=dict(targets=[dict(seq=0,imageIndexes=[0])]))
                await handle.append([user,image]);await handle.flush();await handle.close()
            else:
                version=int(action[1:]) if action in ('v0','v1','v2','v3') else 3
                raw_write('parent',version)
                if action not in ('v0','v1','v2','v3'):
                    child_version=3 if action=='child-v3' else 4
                    descriptor=dict(type='subagent/descriptor',seq=0,time=2,data=dict(version=3,provider='spawn',mode='continuable',label='worker'))
                    events=[descriptor]
                    if action=='child-invalid':events.append(dict(type='image/offload',seq=1,time=2,data=dict(targets=[dict(seq=0,imageIndexes=[0])])))
                    child=raw_write('child',child_version,events,parentSession='parent',origin='subagent',delegationDepth=1)
                before=await backend.stat('parent');result['before']=summarize(before)
                reader=await backend.open('parent','read');initial=await reader.read();await reader.close()
                result.update(preparedTypes=[event['type'] for event in initial['events']],
                    preparedCatalog=[event['data'] for event in initial['events'] if event['type']=='subagent/catalog'],
                    readPublished=Path(backend.locate(header)).exists())
                if action=='membership-add':raw_write('other',4,parentSession='parent',origin='subagent',delegationDepth=1)
                elif action=='membership-remove':child.unlink()
                elif action=='child-changed':
                    with child.open('ab') as file:file.write(b'changed')
                elif action=='unrelated-changed':raw_write('unrelated',4)
                result['revisionChanged']=(await backend.stat('parent'))['revision']!=before['revision']
                try:
                    handle=await backend.open('parent','write');await handle.close();result['published']=True
                except Exception as error:result['publicationError']=getattr(error,'name',type(error).__name__)
            result['after']=summarize(await backend.stat('parent'))
            listed=await backend.list();result['listed']=sorted([item['header']['id'] for item in listed])
            if result.get('publicationError') is None:
                reader=await backend.open('parent','read');restored=await reader.read();await reader.close()
                current=CurrentSession.from_restore('parent',restored['events'],header,0,restored['eventState'],format_version=4,projections=[imageOffloadProjection])
                result['marked']=[block.get('offloaded') is True for message in current.deriveMessages() for block in message['content'] if block['type']=='image']
                result['eventState']=restored['eventState']
        except Exception as error:result['error']=str(error).replace(str(root),'<root>')
        finally:await backend.close()
        result['sourceUnchanged']=all(path.read_bytes()==data for path,data in originals.items() if path.exists() and not(action=='child-changed' and path==child))
        result['stages']=len(list(root.rglob('*.tmp')));result['locks']=len(list(root.rglob('*.lock')))
        results.append(result)
    return results


async def native():return json.loads(json.dumps(await observe(OUTPUT/'files/native')))


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_v4_backend.mts','Actual V4 backend create/read/write/close and child-aware historical preparation, memo revalidation, membership changes and corpus revisions in both encodings. Explicit candidate provider only.',
        [Path(__file__).resolve(),*[ROOT/'dsh/session'/name for name in ('jsonl_backend_current.py','catalog_migration.py','jsonl_current.py','storage_contract.py')]],prepare)
