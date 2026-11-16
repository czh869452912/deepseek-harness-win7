"""Pair the actual target-watch feed against the Python generation owner."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.api.workspace_changes_022 import WorkspaceChangeFeed
from dsh.core.abort import AbortController

CASES=['normal','absent','unrelated','outside-directory','outside-file','outside-became-directory','watch-reject','callback-before','callback-after','preabort','root-error','stat-error','queued-cancel','ready-dispose','close-failure','consumer-return']
CASES += [phase+'-cancel-'+settlement for phase in ('root','target','watch','stat') for settlement in ('return','reject')]

PROGRAM=r'''import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const {WorkspaceChangeFeed}=await import(pathToFileURL(path.join(input.source,'packages/api/workspace-files/src/changes.ts')));const rows=[];
for(const name of input.cases){const failure=new Error('fixture failure'),state={watches:0,closes:0,reported:[]},frames=[],controller=new AbortController(),entered=Promise.withResolvers(),release=Promise.withResolvers(),reported=Promise.withResolvers();let observation,changed;const effects=[];
let info={type:name==='outside-directory'?'directory':'file',version:'current'};const blocked=name.includes('-cancel-');
async function block(phase,signal){if(blocked&&name.startsWith(phase+'-')){entered.resolve();await release.promise;if(name.endsWith('reject'))signal.throwIfAborted()}}
const backend={async resolve(value,options){const phase=value==='/workspace'?'root':'target';await block(phase,options.signal);if(name==='root-error'&&phase==='root')throw failure;return {targetKey:value.startsWith('/')?value:'/workspace/'+value,displayPath:value}},
async stat(target,signal){await block('stat',signal);if(name==='stat-error')throw failure;return info},contains(root,target){return target.targetKey===root.targetKey||target.targetKey.startsWith(root.targetKey+'/')},processPath(target){return target.targetKey},
async watch(target,callback,signal){state.watches++;changed=callback;await block('watch',signal);if(name==='watch-reject')throw failure;if(name==='callback-before')callback(failure);return async()=>{state.closes++;if(name==='close-failure')throw failure}}};
const ctx={fs:backend,on(event,callback){observation=callback},effect(create){effects.push(create())},logger:{error(error){state.reported.push(error.message);reported.resolve()}}};
const feed=new WorkspaceChangeFeed(ctx);if(name==='preabort')controller.abort(failure);const target=name.startsWith('outside-')?'/outside':'target';const iterator=feed.follow('/workspace',target,controller.signal)[Symbol.asyncIterator]();
async function pull(){const row=await iterator.next();frames.push(row.done?{done:true}:row.value)}
let error;try{
 const first=pull();if(blocked){await entered.promise;controller.abort(failure);release.resolve()}await first;
 if(!blocked&&!['preabort','outside-directory','watch-reject','callback-before','root-error','stat-error'].includes(name)){
  if(name==='normal'||name==='unrelated'){if(name==='unrelated')observation({targetKey:'/other',displayPath:'/workspace/target'},{kind:'present',version:'stale'});observation({targetKey:'/workspace/target',displayPath:'elsewhere'},{kind:'absent'});await pull()}
  if(name==='absent'){info=undefined;changed();await pull()}
  if(name==='outside-became-directory'){info={type:'directory',version:'dir'};changed();await pull()}
  if(name==='callback-after'){changed(failure);await pull()}
  if(name==='queued-cancel'){changed();controller.abort(failure);await pull()}
  if(name==='ready-dispose'){await Promise.all(effects.map(fn=>fn()));await pull()}
  if(name==='close-failure'){controller.abort(failure);await reported.promise;await pull()}
  if(name==='consumer-return')await iterator.return();
 }
}catch(e){error={code:e.code??null,message:e.message,exact:e===failure}}
controller.abort(failure);release.resolve();try{await iterator.return()}catch{};await Promise.allSettled(effects.map(fn=>fn()));rows.push({name,frames,error:error??null,state})}
fs.writeFileSync(process.argv[3],JSON.stringify(rows));'''


async def observe():
    rows=[]
    for name in CASES:
        failure=RuntimeError('fixture failure');state=dict(watches=0,closes=0,reported=[]);frames=[];controller=AbortController();entered=asyncio.Event();release=asyncio.Event();reported=asyncio.Event()
        info=NS(type='directory' if name=='outside-directory' else 'file',version='current');effects=[];events={};changed=[None]
        async def block(phase,signal):
            if '-cancel-' in name and name.startswith(phase+'-'):
                entered.set();await release.wait()
                if name.endswith('reject'):signal.throwIfAborted()
        class Backend:
            async def resolve(self,value,options):
                phase='root' if value=='/workspace' else 'target';await block(phase,options['signal'])
                if name=='root-error' and phase=='root':raise failure
                return NS(targetKey=value if value.startswith('/') else '/workspace/'+value,displayPath=value)
            async def stat(self,target,signal):
                await block('stat',signal)
                if name=='stat-error':raise failure
                return info
            def contains(self,root,target):return target.targetKey==root.targetKey or target.targetKey.startswith(root.targetKey+'/')
            def processPath(self,target):return target.targetKey
            async def watch(self,target,callback,signal):
                state['watches']+=1;changed[0]=callback;await block('watch',signal)
                if name=='watch-reject':raise failure
                if name=='callback-before':callback(failure)
                async def close():
                    state['closes']+=1
                    if name=='close-failure':raise failure
                return close
        def report(error):state['reported'].append(getattr(error,'message',str(error)));reported.set()
        backend=Backend();ctx=NS(get=lambda _:backend,on=lambda event,callback:events.update({event:callback}),effect=lambda create,*_:effects.append(create()),logger=NS(error=report))
        feed=WorkspaceChangeFeed(ctx)
        if name=='preabort':controller.abort(failure)
        target='/outside' if name.startswith('outside-') else 'target';iterator=feed.follow('/workspace',target,controller.signal)
        async def pull():
            try:frames.append(await iterator.__anext__())
            except StopAsyncIteration:frames.append(dict(done=True))
        error=None
        try:
            first=asyncio.create_task(pull())
            if '-cancel-' in name:await entered.wait();controller.abort(failure);release.set()
            await first
            if '-cancel-' not in name and name not in ('preabort','outside-directory','watch-reject','callback-before','root-error','stat-error'):
                if name in ('normal','unrelated'):
                    if name=='unrelated':events['fs/observed'](NS(targetKey='/other',displayPath='/workspace/target'),dict(kind='present',version='stale'))
                    events['fs/observed'](NS(targetKey='/workspace/target',displayPath='elsewhere'),dict(kind='absent'));await pull()
                if name=='absent':info=None;changed[0]();await pull()
                if name=='outside-became-directory':info=NS(type='directory',version='dir');changed[0]();await pull()
                if name=='callback-after':changed[0](failure);await pull()
                if name=='queued-cancel':changed[0]();controller.abort(failure);await pull()
                if name=='ready-dispose':await asyncio.gather(*(fn() for fn in effects));await pull()
                if name=='close-failure':controller.abort(failure);await reported.wait();await pull()
                if name=='consumer-return':await iterator.aclose()
        except Exception as caught:error=dict(code=getattr(caught,'code',None),message=getattr(caught,'message',str(caught)),exact=caught is failure)
        controller.abort(failure);release.set()
        try:await iterator.aclose()
        except Exception:pass
        await asyncio.gather(*(fn() for fn in effects),return_exceptions=True);rows.append(dict(name=name,frames=frames,error=error,state=state))
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True)
    (out/'input.json').write_text(json.dumps(dict(source=str(args.source.resolve()),cases=CASES),indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),'--experimental-transform-types',str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(out/'source.log').write_bytes(run.stdout)
    if run.returncode:raise RuntimeError('Source changes probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=asyncio.run(asyncio.wait_for(observe(),30));(out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8')
    differences=[dict(index=i,source=a,native=b) for i,(a,b) in enumerate(zip(source,native)) if a!=b]
    summary=dict(command=command,source_exit_code=run.returncode,cases=len(CASES),difference_count=len(differences),differences=differences)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or len(source)!=len(native):raise AssertionError('workspace changes observations differ')


if __name__=='__main__':main()
