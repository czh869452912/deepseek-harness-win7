/** Adapt platform calls; preserve pinned SDK scan/match/export/raster bodies. */
import {Buffer} from 'buffer';
import {volume,request,received,outputs,resources,hostEnvironment} from './platform.js';
import {run as scan} from '@office/snapshot';
import {run as convert} from '@office/worker';
import {DEFAULT_LIMITS,FONT_FALLBACKS} from '@office/defaults';
globalThis.Buffer=Buffer;

async function main() {
  const input=await(await fetch('request.json')).json();
  input.options={...DEFAULT_LIMITS,initialFontFamilies:[],fontFallbacks:FONT_FALLBACKS,...input.options};
  for(const key of ['loader','data','wasm','metadata'])input.engine[key]=new URL(input.engine[key],location.href).href;
  if(input.options.fontMetadataCacheDirectory!==false)
    throw Error('Browser volume requires host-owned metadata cache.');
  if(input.host)hostEnvironment(input.host);
  volume(input.volume, Object.values(input.engine).filter(value=>typeof value==='string'&&value.startsWith('http:')));
  request({options:input.options,previous:input.previous||[]});await scan();
  const scanned=received().find(value=>'ok' in value);
  if(!scanned?.ok){self.postMessage({...scanned,adapter:resources()});return;}
  if(input.scanOnly){self.postMessage({...scanned,adapter:resources()});return;}
  const bytes=new Uint8Array(await(await fetch(input.inputRoute)).arrayBuffer());
  request({...input,bytes,fontFaces:scanned.snapshot.faces});
  await convert();
  const result=received().find(value=>'ok' in value);
  self.postMessage({...result,fontCache:received().filter(value=>value.kind==='font-cache'),
    files:outputs(),snapshot:scanned.snapshot,adapter:resources()});
}
main();
