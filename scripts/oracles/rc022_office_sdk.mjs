/** Actual original SDK workers, physical fonts and original WASM, never mocks. */
import fs from 'node:fs';import path from 'node:path';import {Worker} from 'node:worker_threads';
import {pathToFileURL} from 'node:url';import vm from 'node:vm';import crypto from 'node:crypto';
const source=path.resolve(process.argv[2]),request=JSON.parse(fs.readFileSync(process.argv[3],'utf8')),out=path.resolve(process.argv[4]);
fs.mkdirSync(out);const pkg=path.join(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit@0.2.3/node_modules/@deepseek-ai/libreoffice-kit');
const engineAssets=path.join(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm/assets');
const text=fs.readFileSync(path.join(pkg,'lib/index.js'),'utf8');
const defaults=vm.runInNewContext(text.slice(text.indexOf('const SANS_CJK_FAMILIES ='),text.indexOf('const FONT_COLLECTION_NAMES ='))+'\n({DEFAULT_LIMITS,FONT_FALLBACKS})');
const options={...defaults.DEFAULT_LIMITS,initialFontFamilies:[],fontFallbacks:defaults.FONT_FALLBACKS,...request.options,
 fontDirectories:request.fontPaths,includeOfficeFonts:request.options.includeOfficeFonts??false,fontMetadataCacheDirectory:false};
async function run(file,data){
 const worker=new Worker(pathToFileURL(path.join(pkg,'lib',file)),{workerData:data,env:{...process.env,...request.host?.env}}),messages=[];
 try{return await new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(Error('Original worker deadline')),60000);
  worker.on('message',value=>{messages.push(value);if('ok' in value){clearTimeout(timer);resolve({value,messages});}});
  worker.on('error',error=>{clearTimeout(timer);reject(error);});worker.on('exit',code=>{clearTimeout(timer);reject(Error('Original worker exited: '+code));});
 });}finally{await worker.terminate();}
}
function encode(value){
 if(ArrayBuffer.isView(value))return {bytes:value.byteLength,sha256:crypto.createHash('sha256').update(value).digest('hex')};
 if(Array.isArray(value))return value.map(encode);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,encode(item)]));
 return value;
}
const result={command:[process.execPath,...process.argv.slice(1)]};
try{
 const scan=await run('font-snapshot-worker.js',{options,previous:[]});result.snapshot=scan.value;
 if(!scan.value.ok||request.scanOnly){result.status='passed';}
 else{
  const engine={backend:'wasm',programDirectory:'/instdir/program',...Object.fromEntries(Object.entries({loader:'dsoffice.cjs',data:'dsoffice.data',wasm:'dsoffice.wasm',metadata:'dsoffice.data.js.metadata'}).map(([key,name])=>[key,path.join(engineAssets,name)]))};
  const operation={...request.operation};if(operation.kind==='images'){operation.outputDir=out;operation.inputPath=request.inputPath;}
  const converted=await run('worker.js',{bytes:fs.readFileSync(request.inputPath),extension:request.extension,operation,options,engine,scratch:out,fontFaces:scan.value.snapshot.faces});
  if(converted.value.output)fs.writeFileSync(path.join(out,'output.'+operation.format),converted.value.output);
  result.result=encode(converted.value);result.fontCache=converted.messages.filter(value=>value.kind==='font-cache');result.status='passed';
 }
}catch(error){result.status='failed';result.error=error.stack;process.exitCode=1;}
finally{fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,error:result.error,ok:result.result?.ok,outputs:result.result?.output}));}
