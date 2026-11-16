"""Pair original ripgrep record ownership against the native adapter."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.util.ripgrep import read_ripgrep_lines
from dsh.core.cleanup import CleanupPromise

PROGRAM=r'''import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';import {Readable,PassThrough} from 'node:stream';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const {readRipgrepLines}=await import(pathToFileURL(path.join(input.source,'packages/util/ripgrep/lib/index.js')));const rows=[];
for(const c of input.cases){const failure=new Error(c.name),state={terminated:0,waited:0},lines=[];
const stdout=c.name==='missing'?undefined:c.name==='provider'?new PassThrough():Readable.from((async function*(){for(const data of c.chunks)yield Buffer.from(data);if(c.name==='stream')throw failure})());
const handle={stdout,done:['missing','provider'].includes(c.name)?Promise.reject(failure):Promise.resolve({exitCode:0,signal:null}),terminate(){state.terminated++},async waitForExit(){state.waited++;return true}};
try{const value=await readRipgrepLines(handle,c.separator,line=>{lines.push(line);if(c.name==='callback')throw failure;return !c.stop});rows.push({name:c.name,value,lines,state})}
catch(error){rows.push({name:c.name,error:error.message,lines,state})}}
fs.writeFileSync(process.argv[3],JSON.stringify(rows));'''

CASES=[dict(name='split',chunks=[[233],[155,170,0,116],[119,111,0,116,97,105,108]],separator='\0'),
    dict(name='invalid',chunks=[[255,0,97,10,98,0]],separator='\0'),dict(name='empty',chunks=[],separator='\n'),
    dict(name='stop',chunks=[list(b'one\ntwo\n'),list(b'three\n')],separator='\n',stop=True),
    dict(name='tail-stop',chunks=[list(b'last')],separator='\n',stop=True)]
CASES += [dict(name=name,chunks=[] if name in ('missing','provider') else [list(b'line\n')],separator='\n') for name in ('missing','callback','stream','provider')]


async def observe():
    rows=[]
    for case in CASES:
        failure=RuntimeError(case['name']);state=dict(terminated=0,waited=0);lines=[]
        class Stream:
            def __init__(self):self.closed=asyncio.Event()
            async def __aiter__(self):
                for data in case['chunks']:yield bytes(data)
                if case['name']=='stream':raise failure
                if case['name']=='provider':await self.closed.wait()
            def destroy(self):self.closed.set()
        class Handle:
            def terminate(self):state['terminated']+=1
            async def waitForExit(self):state['waited']+=1;return True
        async def done():
            if case['name'] in ('missing','provider'):raise failure
            return dict(exitCode=0,signal=None)
        child=Handle();child.stdout=None if case['name']=='missing' else Stream();child.done=CleanupPromise(done())
        def consume(line):
            lines.append(line)
            if case['name']=='callback':raise failure
            return not case.get('stop')
        try:value=await read_ripgrep_lines(child,case['separator'],consume)
        except Exception as error:rows.append(dict(name=case['name'],error=str(error),lines=lines,state=state))
        else:rows.append(dict(name=case['name'],value=value,lines=lines,state=state))
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True)
    (out/'input.json').write_text(json.dumps(dict(source=str(args.source.resolve()),cases=CASES),indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(out/'source.log').write_bytes(result.stdout)
    if result.returncode:raise RuntimeError('actual ripgrep stream probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=asyncio.run(observe())
    (out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8')
    differences=[dict(index=index,source=left,native=right) for index,(left,right) in enumerate(zip(source,native)) if left!=right]
    summary=dict(command=command,source_exit_code=result.returncode,source_rows=len(source),native_rows=len(native),difference_count=len(differences),differences=differences)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or len(source)!=len(native):raise AssertionError('ripgrep stream observations differ')


if __name__=='__main__':main()
