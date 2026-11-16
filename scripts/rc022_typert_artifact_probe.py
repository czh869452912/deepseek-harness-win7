"""Compare current unmodified generated artifacts with actual upstream Zod."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dsh.typert.artifact import read_generated_artifact,UNDEFINED
from dsh.typert.loader import validate_manifest

SAMPLES=[None,True,False,0,1.5,'','x',[],[1],{},dict(name='fresh'),dict(enabled=True,unknown=7),
    dict(registry=None,spec='git+https://example.invalid/o/r.git#'+'a'*40,requestId='request'),
    dict(nested=[1,None,True,dict(text='中文')]),dict(status='cancelled'),
    dict(type='Text',props={},children=['child']),dict(type='Text',props={},children=['child'],extra='strip')]

PROGRAM=r'''import fs from 'node:fs';import {pathToFileURL} from 'node:url';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const rows=[];
for(const file of input.files){const {TYPERT:value}=await import(pathToFileURL(file));
 for(const row of value.invocations){const codecs=[];
  for(const parameter of row.parameters){codecs.push([parameter.wire,parameter.codec]);if(parameter.strictCodec)codecs.push([parameter.wire+':strict',parameter.strictCodec]);}
  codecs.push(['result',row.result]);
  for(const [name,codec] of codecs){const schema=codec.create();
   const validations=[undefined,...input.samples].map(sample=>{const result=schema.safeParse(sample);return result.success?{ok:true,...(result.data===undefined?{undefined:true}:{value:result.data})}:{ok:false};});
   rows.push({package:value.package,endpoint:row.namespace+'/'+row.method,name,typeSymbol:codec.typeSymbol,validations,...(codec.jsonSchema===undefined?{}:{jsonSchema:codec.jsonSchema}),...(codec.jsonSchemaError===undefined?{}:{jsonSchemaError:codec.jsonSchemaError})});
  }
 }
}
fs.writeFileSync(process.argv[3],JSON.stringify(rows));
'''


def observations(files):
    rows=[]
    for path in files:
        value=read_generated_artifact(path);validate_manifest(value['package'],value)
        for row in value['invocations']:
            codecs=[]
            for parameter in row['parameters']:
                codecs.append((parameter['wire'],parameter['codec']))
                if 'strictCodec' in parameter:codecs.append((parameter['wire']+':strict',parameter['strictCodec']))
            codecs.append(('result',row['result']))
            for name,codec in codecs:
                validations=[]
                for sample in [UNDEFINED]+SAMPLES:
                    try:
                        parsed=codec['schema'].parse(sample)
                        validations.append(dict(ok=True,**({'undefined':True} if parsed is UNDEFINED else dict(value=parsed))))
                    except (ValueError,TypeError,KeyError):validations.append(dict(ok=False))
                result=dict(package=value['package'],endpoint=row['namespace']+'/'+row['method'],name=name,
                    typeSymbol=codec['typeSymbol'],validations=validations)
                for key in ('jsonSchema','jsonSchemaError'):
                    if key in codec:result[key]=codec[key]
                rows.append(result)
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True)
    paths=sorted(args.source.resolve().glob('packages/*/*/lib/typert.host.js'));files=[];refused=[]
    for path in paths:
        try:read_generated_artifact(path)
        except ValueError as error:refused.append(dict(path=str(path),reason=str(error)))
        else:files.append(path)
    inputs=dict(files=[str(path) for path in files],samples=SAMPLES,artifacts=[dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths],refused=refused)
    (out/'input.json').write_text(json.dumps(inputs,ensure_ascii=True,indent=2),encoding='utf-8')
    program=out/'source-probe.mjs';program.write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),str(program),str(out/'input.json'),str(out/'source.json')]
    process=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
    (out/'source.log').write_bytes(process.stdout)
    if process.returncode:raise RuntimeError('actual generated artifact import failed; see source.log')
    expected=json.loads((out/'source.json').read_text(encoding='utf-8'));actual=observations(files)
    differences=[dict(index=index,source=left,native=right) for index,(left,right) in enumerate(zip(expected,actual)) if left!=right]
    summary=dict(source_artifacts=len(paths),qualified_readers=len(files),refused=refused,codec_rows=len(expected),validation_cases=len(expected)*(len(SAMPLES)+1),native_rows=len(actual),differences=differences[:20],difference_count=len(differences),command=command,source_exit_code=process.returncode)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=True,indent=2),encoding='utf-8')
    if differences or len(expected)!=len(actual):
        (out/'native.json').write_text(json.dumps(actual,ensure_ascii=True),encoding='utf-8')
        raise AssertionError('actual generated Zod/native observations differ')
    raw=(out/'source.json').read_bytes()
    with gzip.open(str(out/'source-observations.json.gz'),'wb') as stream:stream.write(raw)
    (out/'source.json').unlink()
    summary['source_observation_sha256']=hashlib.sha256(raw).hexdigest()
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=True,indent=2),encoding='utf-8');print(json.dumps(summary))


if __name__=='__main__':main()
