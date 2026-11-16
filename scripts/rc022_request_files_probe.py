"""Request-owned stale-id recovery and normalized-image attribution against Source."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    details=['','file not found','file expired','file does not exist','not created under your account file',
        'invalid file_id','file api is invalid','invalid file','profile expired','FILE-1 DELETED',
        'ſile file not found','fıle expired','fİle expired','fKle expired','file-1 file-10 invalid file id',
        'unsupported image','image cannot be decoded','failed to decode image file-1',
        'image unsupported file-10','cannot read image','file-1 invalid image']
    for separator in ('\n','\r','\u2028','\u2029',' ','x','😀'):
        for count in (19,20,21,39,40,41):
            details.extend(['invalid'+separator*count+'file_id','image'+separator*count+'unsupported'])
    word=json.loads((ROOT/'dsh/resources/file_id_word_unicode16.json').read_text(encoding='utf-8'))['ranges']
    boundaries={'a','1','_','-',' ','/','"','汉','\u0301','\u200d','😀','ſ','K','\ud800','\U0001e4d0','\U00011f02'}
    for start,end in word:
        for value in (start-1,start,end,end+1):
            if 0<=value<=0x10ffff:boundaries.add(chr(value))
    for boundary in sorted(boundaries):
        details.append('file expired invalid image '+boundary+'file-1'+boundary)
    versions=[]
    for index in range(2):
        versions.append(dict(variantId='sha256:'+str(index)*64,attachment=dict(attachmentId='sha256:'+str(index+2)*64,
            name='one "quoted"\n图像' if index==0 else ''),mediaType='image/png' if index==0 else 'image/webp',
            hasAlpha=index==1,width=13+index,height=7+index,bytes=100))
    return dict(details=details,versions=versions)


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


async def observe():
    from dsh.llm.deepseek_request_files import RequestFiles
    from dsh.core.abort import AbortController
    rows=[];inputs=cases()
    for index,detail in enumerate(inputs['details']):
        invalidated=[];pulses=[]
        async def ensure(version,connection,policy,signal):
            return dict(record=dict(fileId='file-1' if version['variantId'][7]=='0' else 'file-10'))
        async def invalidate(records,connection):invalidated.append(copy.deepcopy(records))
        request=RequestFiles(SimpleNamespace(ensureUploaded=ensure,invalidate=invalidate),dict(baseURL='https://example.test',headers={}),{},1000,AbortController().signal,lambda:pulses.append(True))
        request.beginAttempt()
        for occurrence,version in enumerate([inputs['versions'][0],inputs['versions'][1],inputs['versions'][0]]):
            await request.resolve(version,dict(message=occurrence+1,image=1))
        message=request.errorMessage(400,'provider said no',detail)
        other=request.errorMessage(401,'provider said no',detail)
        first=await request.retry(detail);second=await request.retry(detail)
        request.beginAttempt();empty=await request.retry(detail)
        rows.append(dict(index=index,message=message,other=other,retry=[first,second,empty],invalidated=invalidated,pulses=len(pulses)))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_request_files.mts','Actual Source request-owned file resolution, occurrence diagnostics, stale-id classification and bounded retry. Unicode 16 file-id boundaries, UTF-16 indexing, Unicode case folding and JS dot line terminators are exercised without network.',
        [Path(__file__).resolve(),ROOT/'dsh/llm/deepseek_request_files.py',ROOT/'dsh/resources/file_id_word_unicode16.json'],prepare=prepare)
