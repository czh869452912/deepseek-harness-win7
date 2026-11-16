"""Compare original Office output readers on byte-preserved filesystem inputs."""
import argparse
import asyncio
import json
from pathlib import Path
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.core.abort import AbortController
from dsh.office import output

PROGRAM=r'''import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const readers=await import(pathToFileURL(path.join(input.source,'packages/document/office-kit/src/output.ts'))),rows=[];
for(const c of input.cases){const controller=new AbortController(),reason=new Error('fixture cancel');if(c.abort)controller.abort(reason);
try{const bytes=await readers[c.reader](path.join(input.payload,c.name),c.limit,controller.signal);rows.push({name:c.name,bytes:[...bytes]})}catch(error){rows.push({name:c.name,error:{code:error.code??null,message:error.code==='ENOENT'?'<missing>':error.message,exact:error===reason}})}}
fs.writeFileSync(process.argv[3],JSON.stringify(rows));'''


async def observe(cases,payload):
    rows=[]
    for case in cases:
        controller=AbortController();reason=RuntimeError('fixture cancel')
        if case.get('abort'):controller.abort(reason)
        try:data=await getattr(output,dict(readPdf='read_pdf',readPng='read_png',readOutput='read_output')[case['reader']])(payload/case['name'],case['limit'],controller.signal)
        except Exception as error:rows.append(dict(name=case['name'],error=dict(code='ENOENT' if isinstance(error,FileNotFoundError) else getattr(error,'code',None),message='<missing>' if isinstance(error,FileNotFoundError) else getattr(error,'message',str(error)),exact=error is reason)))
        else:rows.append(dict(name=case['name'],bytes=list(data)))
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True);payload=out/'payload';payload.mkdir();cases=[]
    def add(name,reader,data=b'',limit=None,**extra):
        (payload/name).write_bytes(data);cases.append(dict(name=name,reader=reader,limit=len(data) if limit is None else limit,**extra))
    pdf=b'%PDF-1.7\npreview\n%%EOF\n'
    add('pdf','readPdf',pdf);add('ascii-high','readPdf',b'\xa5PDF-1.7\n%%EOF\xa0');add('empty-pdf','readPdf');add('bad-header','readPdf',b'%PDF-x.y\n%%EOF');add('no-trailer','readPdf',b'%PDF-1.7\nmissing');add('nul-trailer','readPdf',pdf+b'\0')
    add('large-pdf','readPdf',pdf,1);add('png','readPng',output.PNG_SIGNATURE+b'payload');add('bad-png','readPng',b'PNG');add('opaque','readOutput',bytes(range(256)));add('empty','readOutput');add('preabort','readPdf',pdf,abort=True)
    os.link(str(payload/'pdf'),str(payload/'hardlink'));cases.append(dict(name='hardlink',reader='readPdf',limit=len(pdf)))
    (payload/'directory').mkdir();cases.append(dict(name='directory',reader='readOutput',limit=100));cases.append(dict(name='missing',reader='readOutput',limit=100))
    (out/'input.json').write_text(json.dumps(dict(source=str(args.source.resolve()),payload=str(payload),cases=cases),indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),'--experimental-transform-types',str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(out/'source.log').write_bytes(run.stdout)
    if run.returncode:raise RuntimeError('Source Office output probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=asyncio.run(observe(cases,payload));(out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8')
    differences=[dict(index=i,source=a,native=b) for i,(a,b) in enumerate(zip(source,native)) if a!=b]
    summary=dict(command=command,source_exit_code=run.returncode,cases=len(cases),difference_count=len(differences),differences=differences)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or len(source)!=len(native):raise AssertionError('Office output observations differ')


if __name__=='__main__':main()
