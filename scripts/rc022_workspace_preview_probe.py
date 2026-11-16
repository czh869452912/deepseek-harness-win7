"""Pair current WorkspaceFiles on actual Source/native local filesystems."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.api.workspace_files_022 import CurrentWorkspaceFiles022
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.core.session.current_session import CurrentSessionPlugin
from dsh.fs.local_current import CurrentFileSystem
from dsh.typert.current import CurrentTypertRegistry

PROGRAM=r'''import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const load=relative=>import(pathToFileURL(path.join(input.source,relative)));
const {Context}=await load('vendor/cordis/lib/index.js'),{LocalFileSystem}=await load('packages/fs/fs-local/lib/index.js'),{WorkspaceFiles}=await load('packages/api/workspace-files/lib/index.js');
const ctx=new Context();await ctx.plugin(LocalFileSystem,{cwd:input.workspace});ctx.provide('sandboxPolicy',{workspaceRoot:input.workspace});
const api=new WorkspaceFiles(ctx,input.caps),signal=new AbortController().signal,scope={sessionId:'session',workspaceRoot:input.workspace};const rows=[];
const normalize=(v,key)=>v instanceof Uint8Array?Array.from(v):Array.isArray(v)?v.map(x=>normalize(x)):v!==null&&typeof v==='object'?Object.fromEntries(Object.entries(v).map(([k,x])=>[k,k==='version'?'<version>':normalize(x,k)])):typeof v==='string'?v.replaceAll(input.payload,'<payload>'):v;
try{for(const c of input.cases){try{rows.push({name:c.name,value:normalize(await api[c.method](scope,...c.args,signal))})}catch(error){rows.push({name:c.name,error:{code:error.code,message:error.message,details:normalize(error.details),...(error.cause?.code?{causeCode:error.cause.code}:{})}})}}}
finally{await ctx.fiber.dispose()}
fs.writeFileSync(process.argv[3],JSON.stringify(rows));'''


def normalize(value,payload,key=None):
    if isinstance(value,bytes):return list(value)
    if isinstance(value,list):return [normalize(item,payload) for item in value]
    if isinstance(value,dict):return {name:'<version>' if name=='version' else normalize(item,payload,name) for name,item in value.items()}
    if isinstance(value,str):return value.replace(str(payload),'<payload>')
    return value


async def observe(inputs):
    root=inputs['workspace'];ctx=Context();await ctx.plugin(CurrentSessionPlugin);await ctx.plugin(CurrentTypertRegistry)
    ctx.set_service('fs',CurrentFileSystem(root));ctx.set_service('sandboxPolicy',SimpleNamespace(workspaceRoot=root))
    await ctx.plugin(CurrentWorkspaceFiles022,inputs['caps']);rows=[];signal=AbortController().signal
    try:
        for case in inputs['cases']:
            try:value=await getattr(ctx.workspaceFiles,case['method'])(dict(sessionId='session',workspaceRoot=root),*case['args'],signal)
            except Exception as error:
                value=dict(message=str(error))
                if hasattr(error,'code'):value['code']=error.code
                if hasattr(error,'details'):value['details']=normalize(error.details,inputs['payload'])
                if getattr(getattr(error,'cause',None),'code',None):value['causeCode']=error.cause.code
                rows.append(dict(name=case['name'],error=value))
            else:rows.append(dict(name=case['name'],value=normalize(value,inputs['payload'])))
    finally:await ctx.fiber.dispose()
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True);payload=out/'payload';workspace=payload/'workspace';workspace.mkdir(parents=True);outside=payload/'outside';outside.mkdir()
    (workspace/'sub').mkdir();(workspace/'base.html').write_bytes(b'base');(workspace/'small.bin').write_bytes(bytes([0,128,255]));(workspace/'large.bin').write_bytes(bytes(range(10)))
    (workspace/'text').write_bytes(b'one\ntwo\nthree\n');(workspace/'nul.bin').write_bytes(b'\0');(workspace/'invalid').write_bytes(b'\xff');(workspace/'sub/item').write_bytes(b'x');(outside/'other').write_bytes(b'other')
    cases=[]
    def add(name,method,*values):cases.append(dict(name=name,method=method,args=list(values)))
    add('complete','readBytes','small.bin',{});add('full-cap','readBytes','large.bin',{})
    for name,window in [('default',{}),('middle',dict(offset=7,length=3)),('eof',dict(offset=10,length=1)),('too-large',dict(length=5)),('bad-offset',dict(offset=-1))]:add('range-'+name,'readBytes','large.bin',dict(range=window))
    add('related','readBytes','../outside/other',dict(baseFile='base.html'))
    for path in ('','/absolute','C:drive','https://host/file','\\server','bad\0name'):add('base-invalid-'+str(len(cases)),'readBytes',path,dict(baseFile='missing'))
    add('page','read','text',dict(offset=2,limit=1));add('page-cap','read','text',dict(limit=3));add('nul','read','nul.bin',{});add('invalid-utf8','read','invalid',{})
    add('list','list','sub');add('list-outside','list',str(outside));add('missing','stat','missing');add('directory','stat','sub');add('empty','stat','')
    if os.name=='nt':
        for name,target in [('inside-link',workspace/'sub'),('outside-link',outside)]:
            result=subprocess.run(['cmd.exe','/c','mklink','/J',str(workspace/name),str(target)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (out/(name+'-creation.log')).write_bytes(result.stdout)
            if result.returncode:raise RuntimeError('owned directory junction creation failed')
        add('list-inside-junction','list','inside-link');add('list-outside-junction','list','outside-link');add('read-junction','readBytes','inside-link',{})
    caps=dict(maxBytes=4,maxFileBytes=5,maxLines=2,maxEntries=2,search=dict(maxResults=512,maxEntries=100000,graceMs=3000,timeoutMs=30000,stderrMaxBytes=65536))
    inputs=dict(source=str(args.source.resolve()),workspace=str(workspace),payload=str(payload),caps=caps,cases=cases)
    (out/'input.json').write_text(json.dumps(inputs,indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90);(out/'source.log').write_bytes(result.stdout)
    if result.returncode:raise RuntimeError('actual Source workspace preview probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=asyncio.run(observe(inputs));(out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8')
    differences=[dict(index=index,source=left,native=right) for index,(left,right) in enumerate(zip(source,native)) if left!=right]
    summary=dict(command=command,source_exit_code=result.returncode,source_rows=len(source),native_rows=len(native),difference_count=len(differences),differences=differences)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or len(source)!=len(native):raise AssertionError('actual workspace previews differ')


if __name__=='__main__':main()
