"""Pair original provider orchestration using an explicit controlled engine seam."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.office.current import CurrentOfficeKit
from dsh.office.output import PNG_SIGNATURE

CASES=['pdf','convert','recalculate','images','bad-pdf','bad-image','image-bytes','type','failed','classified','missing-output','cancel','missing-kit']
PROGRAM=r'''import fs from 'node:fs/promises';import path from 'node:path';import {pathToFileURL} from 'node:url';
const input=JSON.parse(await fs.readFile(process.argv[2],'utf8')),load=p=>import(pathToFileURL(path.join(input.source,p)));
const {Context}=await load('vendor/cordis/lib/index.js'),{OfficeKit,Config,OfficeKitError}=await load('packages/document/office-kit/lib/index.js'),rows=[];
const pdf=Buffer.from('%PDF-1.7\npreview\n%%EOF\n'),png=Buffer.from([137,80,78,71,13,10,26,10]);
for(const name of input.cases){const ctx=new Context(),state={created:0,calls:[],closed:0,scratch:[],options:null},controller=new AbortController(),reason=new Error('cancel');
const converter={async render(options,signal){state.calls.push('pdf');state.scratch.push(path.dirname(options.inputPath));if(name==='cancel'){controller.abort(reason);signal.throwIfAborted()}if(name==='type')throw new TypeError('bad selection');if(name==='failed')throw new Error('private engine detail');if(name==='classified')throw Object.assign(new Error('engine classified'),{code:'timeout'});if(name!=='missing-output')await fs.writeFile(options.outputPath,name==='bad-pdf'?'bad':pdf);return {missingFonts:['Font']}},
async convert(options){state.calls.push('convert');state.scratch.push(path.dirname(options.inputPath));await fs.writeFile(options.outputPath,'text');return {missingFonts:['Font'],pageCount:2}},async recalculate(options){state.calls.push('recalculate');state.scratch.push(path.dirname(options.inputPath));await fs.writeFile(options.outputPath,'xlsx');return {missingFonts:[]}},
async renderImages(options){state.calls.push('images');state.scratch.push(path.dirname(options.inputPath));await fs.mkdir(options.outputDir);const images=[];for(const index of [2,1]){const file=path.join(options.outputDir,index+'.png');await fs.writeFile(file,Buffer.concat([png,Buffer.from([index])]));images.push({index,path:file,width:10,height:20,page:index,byteLength:9})}if(name==='bad-image')images[0].path=path.join(options.outputDir,'..','outside.png');return {images,pageCount:2,dpi:96,missingFonts:['Font']}},async dispose(){state.closed++}};
const config=Config({outputDirectory:path.join(input.payload,'source',name)}),api=new OfficeKit(ctx,config);
// This qualifies Host orchestration, not module resolution or the actual engine.
api.loadKit=async()=>{if(name==='missing-kit')throw new OfficeKitError('unavailable','controlled missing Kit');return {createConverter:async(options)=>{state.created++;const {resolveEnginePackage,...selected}=options;state.options=selected;return converter},resolveEnginePackage:()=>{throw new Error('not used')}}};
const source={extension:'docx',priority:'foreground',source:{key:'a',version:'v1',bytes:4,async read(){return {bytes:new Uint8Array([80,75,3,4]),version:'v1'}}}};let value,error,outputPath;
try{if(['images','bad-image','image-bytes'].includes(name))value=await api.renderImages({...source,maxImages:2,maxPixels:10000,maxDimension:100,maxBytes:name==='image-bytes'?1:18,dpi:96},controller.signal);
else if(name==='convert'||name==='recalculate'){value=await api[name==='convert'?'convertTo':'recalculate']({...source,format:name==='convert'?'txt':'xlsx',output:{owner:'session',name:'result'}},controller.signal);outputPath=value.path;value={...value,path:'<stored>',data:[...await fs.readFile(outputPath)]}}
else{value=await api.convert(source,controller.signal);value.generation='<generation>';value.cacheKey=value.cacheKey.slice(api.generation.length+1)}}catch(e){error={code:e.code??null,message:e.message,exact:e===reason}}
await ctx.fiber.dispose();const scratchGone=await Promise.all(state.scratch.map(p=>fs.access(p).then(()=>false,()=>true)));delete state.scratch;rows.push({name,value:value??null,error:error??null,state,scratchGone,outputGone:outputPath?await fs.access(outputPath).then(()=>false,()=>true):null})}
await fs.writeFile(process.argv[3],JSON.stringify(rows,(_,v)=>v instanceof Uint8Array?[...v]:v));'''


async def observe(payload):
    rows=[]
    for name in CASES:
        ctx=Context();state=dict(created=0,calls=[],closed=0,scratch=[],options=None);controller=AbortController();reason=RuntimeError('cancel');output_path=None;value=None;error=None
        class Engine:
            async def createConverter(self,options):state['created']+=1;state['options']=options;return self
            async def render(self,options,signal):
                state['calls'].append('pdf');state['scratch'].append(str(Path(options['inputPath']).parent))
                if name=='cancel':controller.abort(reason);signal.throwIfAborted()
                if name=='type':raise TypeError('bad selection')
                if name=='failed':raise RuntimeError('private engine detail')
                if name=='classified':
                    failure=RuntimeError('engine classified');failure.code='timeout';raise failure
                if name!='missing-output':Path(options['outputPath']).write_bytes(b'bad' if name=='bad-pdf' else b'%PDF-1.7\npreview\n%%EOF\n')
                return dict(missingFonts=['Font'])
            async def convert(self,options,signal):
                state['calls'].append('convert');state['scratch'].append(str(Path(options['inputPath']).parent));Path(options['outputPath']).write_bytes(b'text');return dict(missingFonts=['Font'],pageCount=2)
            async def recalculate(self,options,signal):
                state['calls'].append('recalculate');state['scratch'].append(str(Path(options['inputPath']).parent));Path(options['outputPath']).write_bytes(b'xlsx');return dict(missingFonts=[])
            async def renderImages(self,options,signal):
                state['calls'].append('images');state['scratch'].append(str(Path(options['inputPath']).parent));directory=Path(options['outputDir']);directory.mkdir();images=[]
                for number in (2,1):
                    path=directory/(str(number)+'.png');path.write_bytes(PNG_SIGNATURE+bytes([number]));images.append(dict(index=number,path=str(path),width=10,height=20,page=number,byteLength=9))
                if name=='bad-image':images[0]['path']=str(directory.parent/'outside.png')
                return dict(images=images,pageCount=2,dpi=96,missingFonts=['Font'])
            async def dispose(self):state['closed']+=1
        ctx.set_service('officeKitEngine',Engine());await ctx.plugin(CurrentOfficeKit,dict(outputDirectory=str(payload/'native'/name)))
        api=ctx.officeKit
        if name=='missing-kit':
            from dsh.office.errors import OfficeKitError
            async def absent():raise OfficeKitError('unavailable','controlled missing Kit')
            api.loadKit=absent
        async def read(signal,maximum):return dict(bytes=b'PK\x03\x04',version='v1')
        request=dict(extension='docx',priority='foreground',source=dict(key='a',version='v1',bytes=4,read=read))
        try:
            if name in ('images','bad-image','image-bytes'):value=await api.renderImages(dict(request,maxImages=2,maxPixels=10000,maxDimension=100,maxBytes=1 if name=='image-bytes' else 18,dpi=96),controller.signal)
            elif name in ('convert','recalculate'):
                value=await getattr(api,'convertTo' if name=='convert' else 'recalculate')(dict(request,format='txt' if name=='convert' else 'xlsx',output=dict(owner='session',name='result')),controller.signal)
                output_path=Path(value['path']);value=dict(value,path='<stored>',data=list(output_path.read_bytes()))
            else:
                value=await api.convert(request,controller.signal);value['generation']='<generation>';value['cacheKey']=value['cacheKey'][len(api.generation)+1:]
        except Exception as caught:error=dict(code=getattr(caught,'code',None),message=getattr(caught,'message',str(caught)),exact=caught is reason)
        finally:await ctx.fiber.dispose()
        scratch_gone=[not Path(path).exists() for path in state.pop('scratch')]
        rows.append(dict(name=name,value=value,error=error,state=state,scratchGone=scratch_gone,outputGone=not output_path.exists() if output_path else None))
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(exist_ok=False,parents=True);payload=out/'payload'
    (out/'input.json').write_text(json.dumps(dict(source=str(args.source.resolve()),cases=CASES,payload=str(payload)),indent=2),encoding='utf-8');(out/'source-probe.mjs').write_text(PROGRAM,encoding='utf-8')
    command=[str(args.node.resolve()),str(out/'source-probe.mjs'),str(out/'input.json'),str(out/'source.json')]
    run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);(out/'source.log').write_bytes(run.stdout)
    if run.returncode:raise RuntimeError('Source Office provider probe failed')
    source=json.loads((out/'source.json').read_text(encoding='utf-8'));native=asyncio.run(asyncio.wait_for(observe(payload),30));native=json.loads(json.dumps(native,default=lambda value:list(value) if isinstance(value,(bytes,bytearray)) else repr(value)))
    (out/'native.json').write_text(json.dumps(native,indent=2),encoding='utf-8');differences=[dict(index=i,source=a,native=b) for i,(a,b) in enumerate(zip(source,native)) if a!=b]
    summary=dict(command=command,source_exit_code=run.returncode,cases=len(CASES),difference_count=len(differences),differences=differences)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
    if differences or len(source)!=len(native):raise AssertionError('Office provider observations differ')


if __name__=='__main__':main()
