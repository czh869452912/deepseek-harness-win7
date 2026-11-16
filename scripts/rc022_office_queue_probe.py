"""Observe bounded Office admission, identities, reuse and shared cancellation."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.core.abort import AbortController
from dsh.office.queue import ConversionQueue,DEFAULTS

CASES=['reuse','digest','file','images','extension','operation','source-version','oversized','unknown','known-too-large','no-retain','lru','aliases','failed','preabort','cancel-shared','cancel-last','priority','evict','background-off','reader-limit','dispose']

PROGRAM=r'''import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const {ConversionQueue}=await import(pathToFileURL(path.join(input.source,'packages/document/office-kit/src/queue.ts'))),rows=[];
for(const name of input.cases){const state={reads:[],converts:[]},results=[],entered=Promise.withResolvers(),release=Promise.withResolvers(),failure=new Error('fixture cancel');let blocked=false;
const changes={'no-retain':{maxCachedBytes:1},lru:{maxCachedEntries:1},aliases:{maxSourceEntries:1},'background-off':{maxBackgroundConversions:0},'reader-limit':{maxReaders:1},priority:{maxConcurrentConversions:1},evict:{maxConcurrentConversions:1,maxQueuedJobs:1},'known-too-large':{maxInputBytes:1}};
const blocking=['digest','cancel-shared','cancel-last','priority','evict','reader-limit','dispose'].includes(name);
const queue=new ConversionQueue({...input.defaults,...changes[name]},'test',async(bytes,request,signal)=>{state.converts.push({bytes:[...bytes],extension:request.extension,operation:request.operation});entered.resolve();if(blocking&&!blocked){blocked=true;await release.promise}if(name==='failed')throw new Error('engine failed');return name==='file'?{kind:'file',data:new Uint8Array([1,2]),pageCount:1,missingFonts:['F']}:name==='images'?{kind:'images',images:[{png:new Uint8Array([3,4]),width:1,height:2,page:1}],dpi:96,pageCount:1,missingFonts:['F']}:{kind:'pdf',pdf:new Uint8Array([37,80,68,70]),missingFonts:['F']}});
const source=(key,byte=1,priority='foreground')=>({extension:'docx',priority,operation:{kind:'pdf'},source:{key,version:'v1',...(name==='unknown'?{}:{bytes:name==='known-too-large'?2:1}),async read(signal,max){state.reads.push([key,max]);return {bytes:new Uint8Array(name==='oversized'?[1,2]:[byte]),version:name==='source-version'?'v2':'v1'}}}});
const capture=async(p)=>{try{return {ok:true,value:await p}}catch(error){return {ok:false,error:{code:error.code??null,message:error.message,exact:error===failure}}}};const read=(request,signal)=>capture(queue.read(request,signal));
try{
 const request=source('a');if(name==='file')request.operation={kind:'convert',format:'txt'};if(name==='images')request.operation={kind:'images',maxBytes:10};
 if(blocking){const c=new AbortController();const first=read(request,c.signal);await entered.promise;
  if(name==='digest'){const same=read(request),equal=read(source('b'));for(let i=0;i<4;i++)await Promise.resolve();release.resolve();results.push(...await Promise.all([first,same,equal]))}
  if(name==='cancel-shared'){const other=read(request);c.abort(failure);results.push(await first);release.resolve();results.push(await other)}
  if(name==='cancel-last'){c.abort(failure);results.push(await first);const next=read(source('a'));release.resolve();results.push(await next)}
  if(name==='priority'){const a=read(source('b',2,'background')),b=read(source('c',3,'background')),promoted=read(source('c',3));release.resolve();results.push(...await Promise.all([first,a,b,promoted]))}
  if(name==='evict'){const discarded=read(source('b',2,'background')),next=read(source('c',3));release.resolve();results.push(...await Promise.all([first,discarded,next]))}
  if(name==='reader-limit'){results.push(await read(source('b',2)));release.resolve();results.push(await first)}
  if(name==='dispose'){const closing=queue.dispose();results.push(await first);release.resolve();await closing;results.push(await read(source('b')))}
 }else if(name==='preabort'){const c=new AbortController();c.abort(failure);results.push(await read(request,c.signal))}
 else if(name==='background-off'){results.push(await read(source('a',1,'background')),await read(request),await read(source('a',1,'background')))}
 else {results.push(await read(request));if(['reuse','file','images','no-retain','failed'].includes(name))results.push(await read(request));if(name==='extension')results.push(await read({...request,extension:'doc'}));if(name==='operation')results.push(await read({...request,operation:{kind:'convert',format:'txt'}}));if(['lru','aliases'].includes(name)){results.push(await read(source('b',2)),await read(request))}}
}finally{release.resolve();await queue.dispose()}
rows.push({name,state,results})}
fs.writeFileSync(process.argv[3],JSON.stringify(rows,(_,value)=>value instanceof Uint8Array?[...value]:value));'''


async def observe():
    rows=[]
    for name in CASES:
        state=dict(reads=[],converts=[]);results=[];entered=asyncio.Event();release=asyncio.Event();failure=RuntimeError('fixture cancel');blocked=False
        changes={'no-retain':dict(maxCachedBytes=1),'lru':dict(maxCachedEntries=1),'aliases':dict(maxSourceEntries=1),'background-off':dict(maxBackgroundConversions=0),'reader-limit':dict(maxReaders=1),'priority':dict(maxConcurrentConversions=1),'evict':dict(maxConcurrentConversions=1,maxQueuedJobs=1),'known-too-large':dict(maxInputBytes=1)}
        blocking=name in ('digest','cancel-shared','cancel-last','priority','evict','reader-limit','dispose')
        async def convert(data,request,signal):
            nonlocal blocked
            state['converts'].append(dict(bytes=list(data),extension=request['extension'],operation=request['operation']));entered.set()
            if blocking and not blocked:blocked=True;await release.wait()
            if name=='failed':raise RuntimeError('engine failed')
            if name=='file':return dict(kind='file',data=bytearray([1,2]),pageCount=1,missingFonts=['F'])
            if name=='images':return dict(kind='images',images=[dict(png=bytearray([3,4]),width=1,height=2,page=1)],dpi=96,pageCount=1,missingFonts=['F'])
            return dict(kind='pdf',pdf=bytearray(b'%PDF'),missingFonts=['F'])
        queue=ConversionQueue(changes.get(name,{}),'test',convert)
        def source(key,byte=1,priority='foreground'):
            async def read(signal,maximum):state['reads'].append([key,maximum]);return dict(bytes=bytes([1,2] if name=='oversized' else [byte]),version='v2' if name=='source-version' else 'v1')
            value=dict(key=key,version='v1',read=read)
            if name!='unknown':value['bytes']=2 if name=='known-too-large' else 1
            return dict(extension='docx',priority=priority,operation=dict(kind='pdf'),source=value)
        async def capture(promise):
            try:return dict(ok=True,value=await promise)
            except Exception as error:return dict(ok=False,error=dict(code=getattr(error,'code',None),message=getattr(error,'message',str(error)),exact=error is failure))
        def read(request,signal=None):return asyncio.create_task(capture(queue.read(request,signal)))
        try:
            request=source('a')
            if name=='file':request['operation']=dict(kind='convert',format='txt')
            if name=='images':request['operation']=dict(kind='images',maxBytes=10)
            if blocking:
                controller=AbortController();first=read(request,controller.signal);await entered.wait()
                if name=='digest':
                    same=read(request);equal=read(source('b'))
                    for _ in range(4):await asyncio.sleep(0)
                    release.set();results.extend(await asyncio.gather(first,same,equal))
                if name=='cancel-shared':
                    other=read(request);controller.abort(failure);results.append(await first);release.set();results.append(await other)
                if name=='cancel-last':
                    controller.abort(failure);results.append(await first);next_read=read(source('a'));release.set();results.append(await next_read)
                if name=='priority':
                    a=read(source('b',2,'background'));b=read(source('c',3,'background'));promoted=read(source('c',3));release.set();results.extend(await asyncio.gather(first,a,b,promoted))
                if name=='evict':
                    discarded=read(source('b',2,'background'));next_read=read(source('c',3));release.set();results.extend(await asyncio.gather(first,discarded,next_read))
                if name=='reader-limit':results.append(await read(source('b',2)));release.set();results.append(await first)
                if name=='dispose':
                    closing=queue.dispose();results.append(await first);release.set();await closing;results.append(await read(source('b')))
            elif name=='preabort':
                controller=AbortController();controller.abort(failure);results.append(await read(request,controller.signal))
            elif name=='background-off':
                results.append(await read(source('a',1,'background')));results.append(await read(request));results.append(await read(source('a',1,'background')))
            else:
                results.append(await read(request))
                if name in ('reuse','file','images','no-retain','failed'):results.append(await read(request))
                if name=='extension':results.append(await read(dict(request,extension='doc')))
                if name=='operation':results.append(await read(dict(request,operation=dict(kind='convert',format='txt'))))
                if name in ('lru','aliases'):results.append(await read(source('b',2)));results.append(await read(request))
        finally:release.set();await queue.dispose()
        rows.append(dict(name=name,state=state,results=results))
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True)
    (out/'input.json').write_text(json.dumps(dict(source=str(args.source.resolve()),cases=CASES,defaults=DEFAULTS),indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),'--experimental-transform-types',str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(out/'source.log').write_bytes(run.stdout)
    if run.returncode:raise RuntimeError('Source Office queue probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=asyncio.run(asyncio.wait_for(observe(),30));native=json.loads(json.dumps(native,default=lambda value:list(value) if isinstance(value,(bytes,bytearray)) else repr(value)))
    (out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8');differences=[dict(index=i,source=a,native=b) for i,(a,b) in enumerate(zip(source,native)) if a!=b]
    summary=dict(command=command,source_exit_code=run.returncode,cases=len(CASES),difference_count=len(differences),differences=differences)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or len(source)!=len(native):raise AssertionError('Office queue observations differ')


if __name__=='__main__':main()
