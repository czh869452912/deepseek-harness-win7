/** Adapt platform calls; preserve pinned SDK scan/match/export/raster bodies. */
import {Buffer} from 'buffer';
import {volume,request,received,outputs,resources,hostEnvironment} from './platform.js';
import {run as scan,readFontMetadataCache,writeFontMetadataCache} from '@office/snapshot';
import {run as convert} from '@office/worker';
import {DEFAULT_LIMITS,FONT_FALLBACKS} from '@office/defaults';
import {validateOutput,pdfPageCount} from '@office/output';
globalThis.Buffer=Buffer;

async function main() {
  const input=await(await fetch('request.json')).json();
  input.options={...DEFAULT_LIMITS,initialFontFamilies:[],fontFallbacks:FONT_FALLBACKS,...input.options};
  for(const key of ['loader','data','wasm','metadata'])input.engine[key]=new URL(input.engine[key],location.href).href;
  if(input.options.fontMetadataCacheDirectory!==false)
    throw Error('Browser volume requires host-owned metadata cache.');
  if(input.host)hostEnvironment(input.host);
  volume(input.volume, Object.values(input.engine).filter(value=>typeof value==='string'&&value.startsWith('http:')));
  let scanned;
  if(input.readySnapshot)scanned={ok:true,snapshot:input.readySnapshot};
  else {
    const cached=input.metadataCache?readFontMetadataCache({...input.options,fontMetadataCacheDirectory:'/metadata'}):[];
    const virtual=record=>({...record,path:'/physical/'+record.path,
      faces:record.faces.map(face=>({...face,path:'/physical/'+face.path}))});
    request({options:input.options,previous:[...cached.map(virtual),...input.previous||[]]});
    await scan();scanned=received().find(value=>'ok' in value);
  }
  if(!scanned?.ok){self.postMessage({...scanned,adapter:resources()});return;}
  if(input.scanOnly){
    if(input.metadataCache){
      const physical=record=>({...record,path:record.path.slice('/physical/'.length),
        faces:record.faces.map(face=>({...face,path:face.path.slice('/physical/'.length)}))});
      writeFontMetadataCache({...input.options,fontMetadataCacheDirectory:'/metadata'},
        scanned.snapshot.records.map(physical),'/metadata/.temporary');
    }
    self.postMessage({...scanned,metadataCache:outputs()['/metadata/font-metadata.json'],adapter:resources()});return;
  }
  const bytes=new Uint8Array(await(await fetch(input.inputRoute)).arrayBuffer());
  request({...input,bytes,fontFaces:scanned.snapshot.faces,
    fontCache:input.generation===undefined||input.generation===scanned.snapshot.generation?input.fontCache:[]});
  await convert();
  const result=received().find(value=>'ok' in value);
  if(result?.ok&&result.output){
    try{validateOutput(result.output,input.operation.format);
      result.metadata={backend:input.engine.backend,missingFonts:result.missingFonts,
        ...input.operation.format==='pdf'?{pageCount:pdfPageCount(result.output)}:{}};
    }catch(error){self.postMessage({ok:false,code:error.code??'failed',error:error.message,
      fontCache:received().filter(value=>value.kind==='font-cache'),adapter:resources()});return;}
  }
  self.postMessage({...result,fontCache:received().filter(value=>value.kind==='font-cache'),
    files:outputs(),snapshot:scanned.snapshot,adapter:resources()});
}
main();
