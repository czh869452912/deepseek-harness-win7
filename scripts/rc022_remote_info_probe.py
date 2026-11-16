"""Pair named method helpers from all actual generated host artifacts."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.typert.artifact import read_generated_artifact,UNDEFINED
from dsh.typert.remote_info import is_typert_remote_method

PROGRAM=r'''import fs from 'node:fs';import {pathToFileURL} from 'node:url';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const rows=[];
const pack=v=>v===undefined?{$undefined:true}:Array.isArray(v)?v.map(pack):v!==null&&typeof v==='object'?Object.fromEntries(Object.keys(v).map(k=>[k,pack(v[k])])):v;
for(const file of input.files){const {TYPERT}=await import(pathToFileURL(file));
 for(const row of TYPERT.invocations){const observation={id:row.id,helper:typeof row.input==='function'&&typeof row.invoke==='function'&&row.result.mode==='strict'&&row.invocation.kind==='direct'};
 if(observation.helper){
 const normal=row.input(),strict=row.input({strict:true});observation.cached=normal===row.input({})&&normal===row.input({strict:false})&&normal===row.input({strict:1})&&strict===row.input({strict:true})&&normal!==strict&&normal.create()===normal.create();
 observation.views=[normal,strict].map(view=>{const filled=value=>Object.fromEntries(row.parameters.map(p=>[p.wire,value]));const omitted=Object.fromEntries(row.parameters.filter(p=>!(p.source==='json'&&p.acceptsUndefined===true)).map(p=>[p.wire,'x']));
 const samples=[undefined,null,[],{},filled('x'),filled(null),filled(true),filled({title:'x',unknown:3}),omitted,{...omitted,unknown:3},filled(undefined)];
 return {projection:pack({jsonSchema:view.jsonSchema,jsonSchemaError:view.jsonSchemaError}),validations:samples.map(sample=>{const r=view.create().safeParse(sample);return r.success?{ok:true,value:pack(r.data)}:{ok:false}})};});
 const accesses=[],signal={signal:'test'};let captured;let receiver;
 const remote=new Proxy({},{get(_,namespace){accesses.push(namespace);receiver=new Proxy({},{get(_,method){accesses.push(method);return function(...values){captured={values:pack(values),receiver:this===receiver};return token}}});return receiver}});const token={returned:'exact'};
 const named=Object.fromEntries(row.parameters.filter((p,i)=>i%2===0).map(p=>[p.wire,{argument:p.wire}]));
 observation.invoked={identity:row.invoke(remote,named,signal)===token,accesses,captured};
 }rows.push(observation);
 }}fs.writeFileSync(process.argv[3],JSON.stringify(rows));'''


def pack(value):
    if value is UNDEFINED:return {'$undefined':True}
    if isinstance(value,list):return [pack(item) for item in value]
    if isinstance(value,dict):return {key:pack(item) for key,item in value.items()}
    return value


def observe(files):
    observations=[]
    for file in files:
        for row in read_generated_artifact(file)['invocations']:
            observation=dict(id=row['id'],helper=is_typert_remote_method(row))
            if observation['helper']:
                normal=row['input']();strict=row['input'](dict(strict=True))
                observation['cached']=(normal is row['input']({}) is row['input'](dict(strict=False)) is row['input'](dict(strict=1)) and strict is row['input'](dict(strict=True)) and normal is not strict and normal.create() is normal.create())
                views=[]
                for view in (normal,strict):
                    def filled(value):return {p['wire']:value for p in row['parameters']}
                    omitted={p['wire']:'x' for p in row['parameters'] if not (p['source']=='json' and p.get('acceptsUndefined') is True)}
                    samples=[UNDEFINED,None,[],{},filled('x'),filled(None),filled(True),filled(dict(title='x',unknown=3)),omitted,dict(omitted,unknown=3),filled(UNDEFINED)]
                    validations=[]
                    for sample in samples:
                        try:validations.append(dict(ok=True,value=pack(view.create().parse(sample))))
                        except (ValueError,TypeError):validations.append(dict(ok=False))
                    views.append(dict(projection=pack(dict(jsonSchema=view.jsonSchema,jsonSchemaError=view.jsonSchemaError)),validations=validations))
                observation['views']=views
                accesses=[];captured={};token=object()
                class Receiver:
                    def __getattr__(self,method):
                        accesses.append(method)
                        def call(*values):captured.update(values=pack(list(values)),receiver=self is receiver);return token
                        return call
                class Remote:
                    def __getattr__(self,namespace):accesses.append(namespace);return receiver
                receiver=Receiver();named={p['wire']:dict(argument=p['wire']) for index,p in enumerate(row['parameters']) if index%2==0}
                identity=row['invoke'](Remote(),named,dict(signal='test')) is token
                observation['invoked']=dict(identity=identity,accesses=accesses,captured=captured)
            observations.append(observation)
    return observations


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True)
    files=sorted(args.source.resolve().glob('packages/*/*/lib/typert.host.js'))
    (out/'input.json').write_text(json.dumps(dict(files=[str(file) for file in files]),indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90);(out/'source.log').write_bytes(result.stdout)
    if result.returncode:raise RuntimeError('actual generated helper probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=observe(files)
    differences=[dict(index=index,source=left,native=right) for index,(left,right) in enumerate(zip(source,native)) if left!=right]
    summary=dict(command=command,source_exit_code=result.returncode,source_rows=len(source),native_rows=len(native),direct_helpers=sum(row['helper'] for row in source),difference_count=len(differences),differences=differences[:10])
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    if differences or len(source)!=len(native):
        (out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8');raise AssertionError('actual generated helpers differ; see summary')
    print(json.dumps(summary))


if __name__=='__main__':main()
