/** Actual pinned public converter with exact source files and original WASM. */
import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';import {execFileSync} from 'node:child_process';
const source=path.resolve(process.argv[2]),request=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
if(execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!=='38a6a5c965aa99ab525161efb7cc5cf1fe62fced' ||
 execFileSync('git',['-C',source,'status','--porcelain','--untracked-files=no'],{encoding:'utf8'}).trim())throw Error('Requires clean pinned Source.');
const pkg=path.join(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit@0.2.3/node_modules/@deepseek-ai/libreoffice-kit');
const wasm=path.join(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm/package.json');
const sdk=await import(pathToFileURL(path.join(pkg,'lib/index.js')));
const converter=await sdk.createConverter({...request.options,resolveEnginePackage(name){if(name.endsWith('-wasm'))return wasm;const error=Error('Not selected');error.code='MODULE_NOT_FOUND';throw error;}});
const rows=[];
try{
 for(const item of request.operations){
  try{rows.push({name:item.name,ok:true,result:await converter[item.kind](item.request)});}
  catch(error){rows.push({name:item.name,ok:false,nameError:error.name,message:error.message,...error.code===undefined?{}:{code:error.code}});}
 }
}finally{await converter.dispose();}
fs.writeFileSync(request.report,JSON.stringify({rows},null,2));console.log(JSON.stringify({rows}));
