"""Pair store paths, byte accounting, eviction, release and startup sweep."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.office.outputs import OutputStore,owner_directory

CASES=['save','evict','too-large','release','dispose','serialized','expiry','sweep']
PROGRAM=r'''import fs from 'node:fs/promises';import path from 'node:path';import {pathToFileURL} from 'node:url';import {createHash,randomUUID} from 'node:crypto';
const input=JSON.parse(await fs.readFile(process.argv[2],'utf8'));const {OutputStore}=await import(pathToFileURL(path.join(input.source,'packages/document/office-kit/src/outputs.ts'))),rows=[];
const exists=p=>fs.access(p).then(()=>true,()=>false);const owner=id=>'session-'+createHash('sha256').update(id).digest('hex').slice(0,24);
for(const name of input.cases){const root=path.join(input.payload,'source',name),warnings=[],results=[],paths=[];let expired,fresh,unknown;
if(name==='sweep'){const base=path.join(root,owner('old'));expired=path.join(base,randomUUID());fresh=path.join(base,randomUUID());unknown=path.join(base,'unknown');for(const p of [expired,fresh,unknown]){await fs.mkdir(p,{recursive:true});await fs.writeFile(path.join(p,'file'),'data')}const old=new Date(Date.now()-120000);await fs.utimes(expired,old,old);await fs.utimes(unknown,old,old)}
const store=new OutputStore({root,retentionMs:name==='expiry'?20:60000,maxBytes:8},m=>warnings.push(m));
async function save(id,file,bytes){try{const p=await store.save(id,file,new Uint8Array(bytes));paths.push(p);results.push({saved:{owner:path.basename(path.dirname(path.dirname(p))),file:path.basename(p),validOutput:/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(path.basename(path.dirname(p))),bytes:[...await fs.readFile(p)]}})}catch(e){results.push({error:{code:e.code??null,message:e.message}})}}
await save('session/a','../report.pdf',[1,2]);
if(name==='evict')await save('b','new',[3,4,5,6,7,8,9]);if(name==='too-large')await save('b','large',Array(9).fill(1));
if(name==='release'){await save('b','other',[3]);await store.release('session/a')}
if(name==='serialized')await Promise.all([save('b','two',[3,4,5,6]),save('c','three',[7,8,9,10])]);
if(name==='expiry')await new Promise(r=>setTimeout(r,50));
if(name==='dispose'){await store.dispose();await save('b','late',[])}
const observed={exists:await Promise.all(paths.map(exists)),warnings:warnings.length};if(name==='sweep')observed.sweep=await Promise.all([expired,fresh,unknown].map(exists));
await store.dispose();observed.afterDispose=await Promise.all(paths.map(exists));rows.push({name,results,observed})}
await fs.writeFile(process.argv[3],JSON.stringify(rows));'''


async def observe(payload):
    rows=[]
    for name in CASES:
        root=payload/'native'/name;warnings=[];results=[];paths=[];generated=[]
        if name=='sweep':
            base=root/owner_directory('old');generated=[base/str(uuid.uuid4()),base/str(uuid.uuid4()),base/'unknown']
            for path in generated:path.mkdir(parents=True);(path/'file').write_bytes(b'data')
            old=time.time()-120
            for path in (generated[0],generated[2]):os.utime(str(path),(old,old))
        store=OutputStore(dict(root=str(root),retentionMs=20 if name=='expiry' else 60000,maxBytes=8),warnings.append)
        async def save(owner,name,data):
            try:
                path=Path(await store.save(owner,name,bytearray(data)));paths.append(path)
                results.append(dict(saved=dict(owner=path.parent.parent.name,file=path.name,validOutput=uuid.UUID(path.parent.name).version==4,bytes=list(path.read_bytes()))))
            except Exception as error:results.append(dict(error=dict(code=getattr(error,'code',None),message=getattr(error,'message',str(error)))))
        try:
            await save('session/a','../report.pdf',[1,2])
            if name=='evict':await save('b','new',[3,4,5,6,7,8,9])
            if name=='too-large':await save('b','large',[1]*9)
            if name=='release':await save('b','other',[3]);await store.release('session/a')
            if name=='serialized':await asyncio.gather(save('b','two',[3,4,5,6]),save('c','three',[7,8,9,10]))
            if name=='expiry':await asyncio.sleep(.05)
            if name=='dispose':await store.dispose();await save('b','late',[])
            observed=dict(exists=[path.exists() for path in paths],warnings=len(warnings))
            if name=='sweep':observed['sweep']=[path.exists() for path in generated]
        finally:await store.dispose()
        observed['afterDispose']=[path.exists() for path in paths];rows.append(dict(name=name,results=results,observed=observed))
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True);payload=out/'payload'
    (out/'input.json').write_text(json.dumps(dict(source=str(args.source.resolve()),cases=CASES,payload=str(payload)),indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),'--experimental-transform-types',str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(out/'source.log').write_bytes(run.stdout)
    if run.returncode:raise RuntimeError('Source Office output store probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=asyncio.run(asyncio.wait_for(observe(payload),30));(out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8')
    differences=[dict(index=i,source=a,native=b) for i,(a,b) in enumerate(zip(source,native)) if a!=b]
    summary=dict(command=command,source_exit_code=run.returncode,cases=len(CASES),difference_count=len(differences),differences=differences)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or len(source)!=len(native):raise AssertionError('Office output store observations differ')


if __name__=='__main__':main()
