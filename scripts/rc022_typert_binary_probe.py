"""Compare actual generated selected-byte encoding and result parsing."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.typert.artifact import read_generated_artifact,UNDEFINED
from dsh.typert.artifact_binary import is_bytes

PROGRAM=r'''import fs from 'node:fs';import {pathToFileURL} from 'node:url';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const rows=[];
const pack=v=>v===undefined?{$undefined:true}:typeof v==='function'?{$function:true}:v instanceof Uint8Array?{$bytes:Array.from(v)}:Array.isArray(v)?v.map(pack):v!==null&&typeof v==='object'?Object.fromEntries(Object.keys(v).map(k=>[k,pack(v[k])])):v;
for(const file of input.files){const {TYPERT}=await import(pathToFileURL(file));const row=TYPERT.invocations.find(r=>r.result.encode);
 for(const name of input.cases){const keys=[];let original;
 const data=()=>new Uint8Array([0,127,255]);const valid=()=>({offset:0,data:data(),eof:true,absolutePath:'C:\\example',version:'opaque',missingFonts:[],generation:'g'});
 switch(name){
 case 'valid':original=valid();break;case 'extra-bytes':original={...valid(),extra:data()};break;
 case 'top-bytes':original=data();break;case 'array':original=[data()];break;
 case 'null':original=null;break;case 'undefined':original=undefined;break;case 'string':original='value';break;
 case 'number':original=3;break;case 'boolean':original=false;break;case 'empty':original={};break;
 case 'data-null':original={data:null};break;case 'data-object':original={data:{nested:data()}};break;
 case 'data-string':original={data:'bytes'};break;case 'empty-bytes':original={data:new Uint8Array(0)};break;
 case 'json-object':original={toJSON(key){keys.push(key);return valid()}};break;
 case 'json-bytes':original={toJSON(key){keys.push(key);return data()}};break;
 case 'json-null':original={toJSON(key){keys.push(key);return null}};break;
 case 'json-self':original={...valid(),toJSON(key){keys.push(key);return this}};break;
 case 'class':original=new(class{constructor(){this.data=data();this.extra=3}})();break;
 case 'date':original=new Date('2020-01-02T03:04:05.000Z');break;
 }
 const attachments=[];const encoded=row.result.encode(original,(bytes,path)=>{attachments.push({bytes:pack(bytes),path});return null});
 const parsed=row.result.create().safeParse(original);rows.push({package:TYPERT.package,name,encoded:pack(encoded),attachments,keys,...(parsed.success?{decoded:pack(parsed.data)}:{decodeError:true}),...(original&&original.data instanceof Uint8Array?{unchangedBytes:pack(original.data)}:{})});
 }}fs.writeFileSync(process.argv[3],JSON.stringify(rows));'''

CASES=['valid','extra-bytes','top-bytes','array','null','undefined','string','number','boolean','empty','data-null','data-object','data-string','empty-bytes','json-object','json-bytes','json-null','json-self','class','date']


def pack(value):
    if value is UNDEFINED:return {'$undefined':True}
    if callable(value):return {'$function':True}
    if is_bytes(value):return {'$bytes':list(bytes(value))}
    if isinstance(value,list):return [pack(item) for item in value]
    if isinstance(value,dict):return {key:pack(item) for key,item in value.items()}
    return value


def observe(files):
    rows=[]
    for file in files:
        artifact=read_generated_artifact(file);codec=next(row['result'] for row in artifact['invocations'] if 'encode' in row['result'])
        for name in CASES:
            keys=[]
            def data():return bytes([0,127,255])
            def valid():return dict(offset=0,data=data(),eof=True,absolutePath='C:\\example',version='opaque',missingFonts=[],generation='g')
            values={'valid':valid(),'extra-bytes':dict(valid(),extra=data()),'top-bytes':data(),'array':[data()],
                'null':None,'undefined':UNDEFINED,'string':'value','number':3,'boolean':False,'empty':{},
                'data-null':dict(data=None),'data-object':dict(data=dict(nested=data())),'data-string':dict(data='bytes'),'empty-bytes':dict(data=b'')}
            if name.startswith('json-'):
                def to_json(key):
                    keys.append(key)
                    return {'json-object':valid(),'json-bytes':data(),'json-null':None,'json-self':original}[name]
                original=dict(valid(),toJSON=to_json) if name=='json-self' else dict(toJSON=to_json)
            elif name=='class':
                class Value:pass
                original=Value();original.data=data();original.extra=3
            elif name=='date':original=datetime.datetime(2020,1,2,3,4,5,tzinfo=datetime.timezone.utc)
            else:original=values[name]
            attachments=[]
            def write_bytes(value,path):attachments.append(dict(bytes=pack(value),path=path));return None
            encoded=codec['encode'](original,write_bytes)
            row=dict(package=artifact['package'],name=name,encoded=pack(encoded),attachments=attachments,keys=keys)
            try:row['decoded']=pack(codec['create']().parse(original))
            except (TypeError,ValueError):row['decodeError']=True
            if isinstance(original,dict) and is_bytes(original.get('data')):row['unchangedBytes']=pack(original['data'])
            elif name=='class':row['unchangedBytes']=pack(original.data)
            rows.append(row)
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    files=[args.source.resolve()/('packages/'+name+'/lib/typert.host.js') for name in ('api/workspace-files','document/office-kit')]
    inputs=dict(files=[str(file) for file in files],cases=CASES,sha256=[hashlib.sha256(file.read_bytes()).hexdigest() for file in files])
    (out/'input.json').write_text(json.dumps(inputs,indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(out/'source.log').write_bytes(result.stdout)
    if result.returncode:raise RuntimeError('actual generated byte probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=observe(files)
    (out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8')
    differences=[dict(index=index,source=left,native=right) for index,(left,right) in enumerate(zip(source,native)) if left!=right]
    summary=dict(command=command,source_exit_code=result.returncode,source_rows=len(source),native_rows=len(native),difference_count=len(differences),differences=differences)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or len(source)!=len(native):raise AssertionError('generated byte observations differ')


if __name__=='__main__':main()
