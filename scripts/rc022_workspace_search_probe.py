"""Observe actual Source search and Unicode casing beside the native adapter."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.api.workspace_search import DEFAULTS,search_workspace
from dsh.cordis.text import lower_js
from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise

PROGRAM=r'''import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';import {Readable,PassThrough} from 'node:stream';import {createHash} from 'node:crypto';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const {searchWorkspace}=await import(pathToFileURL(path.join(input.source,'packages/api/workspace-files/src/search.ts')));const rows=[];
for(const c of input.cases){const failure=new Error('cancelled'),controller=new AbortController(),state={terminated:0,waited:0,spawns:[]};if(c.name==='preabort')controller.abort(failure);
const runtime={spawn(spec){state.spawns.push({...spec,argv:['<packaged-rg>',...spec.argv.slice(1)],signal:'<combined>'});if(c.name==='launch')throw new Error('launch');
const blocked=['timeout','cancel'].includes(c.name);const stdout=blocked?new PassThrough():Readable.from((async function*(){for(const chunk of c.chunks)yield Buffer.from(chunk);if(c.name==='stream')throw new Error('stream')})());
let resolve;const done=blocked?new Promise(r=>resolve=r):Promise.resolve(c.outcome);const handle={stdout,collected:{stderr:{readFrom:()=>({text:c.stderr??''})}},done,terminate(){state.terminated++;if(blocked){stdout.end();resolve({exitCode:null,signal:'SIGTERM'})}},async waitForExit(){state.waited++;return true}};
spec.signal.addEventListener('abort',()=>handle.terminate(),{once:true});if(c.name==='cancel')queueMicrotask(()=>controller.abort(failure));return handle}};
try{rows.push({name:c.name,value:await searchWorkspace(runtime,c.spec,controller.signal),state})}catch(e){rows.push({name:c.name,error:{code:e.code??null,message:e.message,exact:e===failure},state})}}
const scalar=Array.from({length:0x110000},(_,i)=>i>=0xd800&&i<=0xdfff?'':String.fromCodePoint(i)).join('');
const contexts=input.contexts.map(value=>[value,value.toLowerCase()]);
fs.writeFileSync(process.argv[3],JSON.stringify({rows,unicode:{version:process.versions.unicode,sha256:createHash('sha256').update(scalar.toLowerCase()).digest('hex'),contexts}}));'''


def cases():
    base=dict(DEFAULTS,cwd='/workspace',query='button',excludedPaths=['[x]','a/b!','a\\b*?{}'],includeHidden=True,respectGitignore=False)
    values=[]
    def add(name,paths=None,**overrides):
        row=dict(name=name,spec=dict(base,**overrides.pop('spec',{})),chunks=[list(('\0'.join(paths or [])+'\0').encode('utf-8'))] if paths else [],outcome=dict(exitCode=0,signal=None))
        row.update(overrides);values.append(row)
    add('matches',['src/button-group/a','src/button-group/b','BUTTON','src/deep/button.ts','x','button-group/a'])
    add('path',['src/button/a','src/deep/button','SRC/BUTTON/z'],spec=dict(query='src/button'))
    add('unicode',['\u1c8a','A\u03a3','A\u03a3B'],spec=dict(query='\u1c89'))
    add('sigma',['A\u03a3','A\u03a3B'],spec=dict(query='a\u03c2'))
    add('utf16',['\ue000-match','\U00010400-match'],spec=dict(query='match'))
    add('result-cap',['button','button2'],spec=dict(maxResults=1))
    add('scan-exact',['button','button2'],spec=dict(maxEntries=2))
    add('scan-extra',['button','button2','button3'],spec=dict(maxEntries=2))
    add('partial',['button'],outcome=dict(exitCode=2,signal=None))
    add('no-match',outcome=dict(exitCode=1,signal=None),spec=dict(includeHidden=False,respectGitignore=True))
    for name,outcome in [('bad-code',dict(exitCode=3,signal=None)),('signal',dict(exitCode=None,signal='SIGTERM')),('missing-fields',{}),('bool-code',dict(exitCode=True,signal=None))]:
        add(name,['button'],outcome=outcome,stderr=' \ufeffdiagnostic\n')
    for name in ('launch','stream','timeout','cancel','preabort'):add(name,spec=dict(timeoutMs=2 if name=='timeout' else 30000))
    return values


CONTEXTS=['A\u03a3','A\u03a3B','\u1c89\u0345\u03a3','A\u03a3\u1c89','\U00010400\u03a3','\u03a3\u0345','A\u0345\u03a3\u0345','A\u03a3\u0345B','\u0130\u1c89']


async def observe(rows):
    result=[]
    for case in rows:
        failure=RuntimeError('cancelled');controller=AbortController();state=dict(terminated=0,waited=0,spawns=[])
        if case['name']=='preabort':controller.abort(failure)
        def spawn(spec):
            saved=dict(spec,argv=['<packaged-rg>']+spec['argv'][1:],signal='<combined>');state['spawns'].append(saved)
            if case['name']=='launch':raise RuntimeError('launch')
            blocked=case['name'] in ('timeout','cancel');closed=asyncio.Event();done=asyncio.get_running_loop().create_future()
            if not blocked:done.set_result(case['outcome'])
            class Stream:
                async def __aiter__(self):
                    for chunk in case['chunks']:yield bytes(chunk)
                    if case['name']=='stream':raise RuntimeError('stream')
                    if blocked:await closed.wait()
                def destroy(self):closed.set()
            class Handle:
                stdout=Stream();collected=dict(stderr=SimpleNamespace(readFrom=lambda _:dict(text=case.get('stderr',''))))
                def terminate(self):
                    state['terminated']+=1
                    if blocked:
                        closed.set()
                        if not done.done():done.set_result(dict(exitCode=None,signal='SIGTERM'))
                async def waitForExit(self):state['waited']+=1;return True
            handle=Handle();handle.done=done
            spec['signal'].add_listener('abort',lambda _:handle.terminate())
            if case['name']=='cancel':asyncio.get_running_loop().call_soon(controller.abort,failure)
            return handle
        try:value=await search_workspace(SimpleNamespace(spawn=spawn),case['spec'],controller.signal)
        except Exception as error:result.append(dict(name=case['name'],error=dict(code=getattr(error,'code',None),message=getattr(error,'message',str(error)),exact=error is failure),state=state))
        else:result.append(dict(name=case['name'],value=value,state=state))
    return dict(rows=result,unicode=dict(version='16.0',sha256=hashlib.sha256(lower_js(''.join(chr(code) for code in range(0x110000) if not 0xd800<=code<=0xdfff)).encode('utf-8')).hexdigest(),contexts=[[value,lower_js(value)] for value in CONTEXTS]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True);rows=cases()
    (out/'input.json').write_text(json.dumps(dict(source=str(args.source.resolve()),cases=rows,contexts=CONTEXTS),indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(out/'source.log').write_bytes(run.stdout)
    if run.returncode:raise RuntimeError('actual Source workspace search probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=asyncio.run(observe(rows));(out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8')
    differences=[dict(index=i,source=a,native=b) for i,(a,b) in enumerate(zip(source['rows'],native['rows'])) if a!=b]
    summary=dict(command=command,source_exit_code=run.returncode,cases=len(rows),difference_count=len(differences),differences=differences,unicode_match=source['unicode']==native['unicode'],unicode=source['unicode'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or not summary['unicode_match'] or len(source['rows'])!=len(native['rows']):raise AssertionError('workspace search observations differ')


if __name__=='__main__':main()
