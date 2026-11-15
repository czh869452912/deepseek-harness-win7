"""Pair strict V4 files and real isolated verification during generation publication."""
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_image_catalog_probe import catalog_cases

OUTPUT=None


def cases():
    lifecycle=next(row['events'] for row in catalog_cases() if row['name']=='lifecycle-valid')
    header=dict(type='session',version=4,id='session',createdAt=1,isSeeded=False,delegationDepth=0)
    user=dict(type='user/message',seq=0,time=1,data=dict(id='user',role='user',source=dict(kind='user'),content=[dict(type='image',attachment={})]),surfaceOp='append')
    image=dict(type='image/offload',seq=1,time=1,data=dict(targets=[dict(seq=0,imageIndexes=[0])]))
    rows=[]
    def add(name,events=None,**options):rows.append(dict(name=name,header=copy.deepcopy(header),events=copy.deepcopy([user,image] if events is None else events),**options))
    add('valid',worker=True);add('lifecycle',lifecycle,worker=True);add('empty',[])
    add('plugin',[dict(type='plugin:test/state',seq=0,time=1,data=dict(value=1),ignorable=True)])
    add('opaque-unknown',[dict(type='future/unknown',seq=0,time=1,data={},ignorable=True)])
    add('unknown',[dict(type='future/unknown',seq=0,time=1,data={})])
    add('missing-surface');rows[-1]['events'][0].pop('surfaceOp')
    add('invalid-image',worker=True);rows[-1]['events'][1]['data']['targets'][0]['imageIndexes']=[1]
    add('duplicate-image',[user,image,dict(image,seq=2)])
    add('image-extra');rows[-1]['events'][1]['data']['extra']=True
    add('unopened-lifecycle',[dict(type='turn/end',seq=0,time=1,data=dict(turn=1))])
    add('unresolved-tool',lifecycle[:7]+[dict(type='step/end',seq=7,time=1,data=dict(turn=1,step=1))])
    add('bad-stream',lifecycle,worker=True);rows[-1]['events'][5]['data']['stream']=[dict(type='chunk',chunk=dict(type='invalid'))]
    add('seq-gap');rows[-1]['events'][1]['seq']=2
    add('bad-id',expectedId='other');add('bad-count',expectedEventCount=3)
    for version in (3,5):add('version-%s'%version);rows[-1]['header']['version']=version
    add('retired-policy');rows[-1]['header']['approvalPolicy']='never'
    add('extra-header');rows[-1]['header']['extra']=True
    add('torn-line',tail='{"type":')
    add('bad-json',tail='bad\n')
    add('empty-line',tail='\n')
    add('empty-file',physical='empty')
    add('header-no-newline',physical='header-no-newline')
    add('torn-frame',physical='torn-frame')
    add('combined-frame',physical='combined-frame')
    add('prefix-append',tail='unvalidated append',prefix='valid',worker=True,expectedId='ignored',expectedEventCount=999)
    add('prefix-short',prefix='short');add('prefix-different',prefix='different')
    return [dict(row,compression=compression) for compression in ('none','zstd') for row in rows
            if compression=='zstd' or row.get('physical') not in ('torn-frame','combined-frame')]


def prepare(output):
    global OUTPUT
    OUTPUT=output;path=output/'input.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


def physical(row):
    from dsh.session.jsonl_zstd import compress_frame
    header=(json.dumps(row['header'],separators=(',',':'))+'\n').encode('utf-8')
    events=''.join(json.dumps(event,separators=(',',':'))+'\n' for event in row['events']).encode('utf-8')
    tail=row.get('tail','').encode('utf-8')
    prefix=header+events if row['compression']=='none' else compress_frame(header)+compress_frame(events)
    data=prefix+tail if row['compression']=='none' else compress_frame(header)+compress_frame(events+tail)
    mode=row.get('physical')
    if mode=='empty':data=b''
    elif mode=='header-no-newline':data=header[:-1] if row['compression']=='none' else compress_frame(header[:-1])
    elif mode=='torn-frame':data=data[:-1]
    elif mode=='combined-frame':data=compress_frame(header+events)
    if row.get('prefix'):
        # Prefix mode accepts arbitrary following bytes, including an incomplete frame.
        data=prefix+tail
        expected=dict(bytes=len(prefix),digest=hashlib.sha256(prefix).hexdigest())
        if row['prefix']=='short':expected['bytes']=len(data)+1
        elif row['prefix']=='different':expected['digest']='0'*64
    else:expected=None
    return data,expected


async def observe(workspace):
    from dsh.session.generation import createJsonlGenerationRuntime
    from dsh.session.generation_verifier import verifyCurrentGenerationInWorker
    runtime=createJsonlGenerationRuntime(dict(formatVersion=4));results=[];workspace.mkdir(parents=True,exist_ok=True)
    for index,row in enumerate(cases()):
        path=workspace/('%s-%s.bin'%(index,row['name']));data,prefix=physical(row);path.write_bytes(data)
        result=dict(name=row['name'],compression=row['compression'])
        for action in ('direct','worker') if row.get('worker') else ('direct',):
            try:
                args=[str(path),row['compression'],row.get('expectedId','session'),row.get('expectedEventCount',len(row['events'])),prefix]
                value=await (runtime.verify(*args) if action=='direct' else verifyCurrentGenerationInWorker(*args,format_version=4))
                size=prefix['bytes'] if prefix else len(data)
                result[action]=dict(bytes=value['bytes']==size,digest=value['digest']==hashlib.sha256(data[:size]).hexdigest())
            except Exception as error:result[action]=str(error).replace(str(path),'<file>')
        results.append(result)
    from dsh.session.format_catalog import createSessionFormatCatalogWithChildren
    from dsh.session.jsonl_current import generationLogFilename
    from dsh.session.jsonl_zstd import compress_frame
    for compression in ('none','zstd'):
        for version in range(4):
            root=workspace/('publish-%s-%s'%(compression,version));root.mkdir()
            source=root/generationLogFilename(version,compression);target=root/generationLogFilename(4,compression)
            header=dict(type='session',version=version,id='parent',createdAt=1,delegationDepth=0)
            header.update(dict(seedLength=0) if version<2 else dict(isSeeded=False))
            raw=(json.dumps(header,separators=(',',':'))+'\n').encode('utf-8');original=raw if compression=='none' else compress_frame(raw)
            source.write_bytes(original);catalog=createSessionFormatCatalogWithChildren([])
            adapter=dict(currentVersion=4,createRestore=lambda value:catalog.createRestore(value,dict(validation='transformed',recovery='recoverable')),
                encodeHeader=catalog.encodeCurrentHeader,encodeEvent=catalog.encodeCurrentEvent)
            result=dict(name='publish-%s'%version,compression=compression)
            try:
                prepared=await runtime.prepare(dict(sourcePath=str(source),sourceVersion=version,currentPath=str(target),compression=compression,format=adapter))
                await prepared.publish();result['published']=True
                verified=await runtime.verify(str(target),compression,'parent',len(prepared.artifact['events']))
                result['verified']=verified['bytes']==target.stat().st_size
            except Exception as error:result['error']=str(error).replace(str(root),'<root>')
            result.update(sourceUnchanged=source.read_bytes()==original,target=target.exists(),stages=len(list(root.glob('*.tmp'))));results.append(result)
    return results


async def native():return await observe(OUTPUT/'files/native')


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_v4_generation.mts','Actual V4 strict plaintext/Zstandard framing, installed vocabulary/surface/lifecycle/image interpretation and isolated worker validation; native v0-v3 to V4 publication uses its default fresh verifier.',
        [Path(__file__).resolve(),*[ROOT/'dsh/session'/name for name in ('generation.py','generation_verifier.py','jsonl_current.py','storage_contract.py')]],prepare)
