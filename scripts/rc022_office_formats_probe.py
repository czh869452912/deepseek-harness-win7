"""Compare actual Office tool admission and model content projections."""
import argparse
import itertools
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.office import formats,content

PROGRAM=r'''import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),base=path.join(input.source,'packages/document/tool-office/src');
const f=await import(pathToFileURL(path.join(base,'formats.ts'))),c=await import(pathToFileURL(path.join(base,'content.ts'))),rows=[];
for(const sample of input.cases){try{const value=await ({...f,...c})[sample.method](...sample.args);rows.push(value===undefined?{ok:true}:{ok:true,value})}catch(e){rows.push({error:e.message})}}
fs.writeFileSync(process.argv[3],JSON.stringify(rows));'''

MAPPING=dict(extensionOf=formats.extension_of,inputFamily=formats.input_family,checkParameterNames=formats.check_parameter_names,
    checkRenderArguments=formats.check_render_arguments,checkConversionArguments=formats.check_conversion_arguments,
    renderFileContent=content.render_file_content,renderImagesContent=content.render_images_content)


def cases():
    rows=[]
    def add(method,*args):rows.append(dict(method=method,args=list(args)))
    for name in ('file.docx','FILE.DOCX','C:\\dir.xls\\file.PDF','/foo.bar/file','.docx','file.','noextension','path\\.xlsx','path\\file.a.b','\u1c89'):
        add('extensionOf',name)
        for operation in ('render','convert','recalculate'):add('inputFamily',operation,name)
    for extension in formats.FAMILIES:
        for operation in ('render','convert','recalculate'):add('inputFamily',operation,'file.'+extension.upper())
    for tool in formats.PARAMETER_NAMES:
        for key in ('input','format','pages','sheet','range','dpi','unknown'):
            add('checkParameterNames',tool,{key:'fixture'},formats.PARAMETER_NAMES)
    for family,args in itertools.product(('text','spreadsheet','presentation','pdf'),({},dict(pages=[]),dict(pages=[1]),dict(pages=[1,1]),dict(pages=[0]),dict(pages=[True]),dict(pages=[1.5]),dict(sheet=''),dict(sheet='\ufeff'),dict(sheet='Sheet'),dict(range='A1'),dict(sheet='Sheet',range='A1'),dict(dpi=23),dict(dpi=24),dict(dpi=600),dict(dpi=601),dict(dpi=24.5))):add('checkRenderArguments',args,family)
    for family,format,sheet in itertools.product(('text','spreadsheet','presentation'),formats.OUTPUT_FORMATS+[None],(None,'','\ufeff','Sheet')):
        args=dict(input='file',format=format)
        if sheet is not None:args['sheet']=sheet
        add('checkConversionArguments',args,family)
    for operation,pages,fonts in itertools.product(('convert','recalculate'),(None,0,1,2),([],['Font','Other'])):
        value=dict(operation=operation,path='C:\\input',file='C:\\output',format='xlsx',bytes=123,missingFonts=fonts)
        if pages is not None:value['pageCount']=pages
        add('renderFileContent',value)
    image=dict(attachmentId='image',mediaType='image/png',bytes=3,width=10,height=20)
    for images,fonts in itertools.product(([],[image],[dict(image,page=1)],[dict(image,sheet='Sheet')],[dict(image,sheet='Sheet',range='A1',originalDimensions=dict(width=100,height=200))],[dict(image,page=2),dict(image,sheet='Sheet')]),([],['Font'])):
        add('renderImagesContent',dict(operation='render',path='C:\\input',pageCount=3,dpi=96,images=images,missingFonts=fonts))
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True);samples=cases()
    (out/'input.json').write_text(json.dumps(dict(source=str(args.source.resolve()),cases=samples),indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(out/'source.log').write_bytes(run.stdout)
    if run.returncode:raise RuntimeError('Source Office formats/content probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=[]
    for sample in samples:
        try:value=MAPPING[sample['method']](*sample['args'])
        except Exception as error:native.append(dict(error=str(error)))
        else:native.append(dict(ok=True) if value is None else dict(ok=True,value=value))
    (out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8');differences=[dict(index=i,sample=samples[i],source=a,native=b) for i,(a,b) in enumerate(zip(source,native)) if a!=b]
    summary=dict(command=command,source_exit_code=run.returncode,cases=len(samples),difference_count=len(differences),differences=differences)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or len(source)!=len(native):raise AssertionError('Office formats/content observations differ')


if __name__=='__main__':main()
