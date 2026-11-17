/** Probe the pinned Office WASM carrier in Chromium 108 with a controlled Arial font. */
import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import {pathToFileURL} from 'node:url';import crypto from 'node:crypto';import {parseArgs} from 'node:util';import {execFileSync} from 'node:child_process';
const {values}=parseArgs({options:{source:{type:'string'},browser:{type:'string'},output:{type:'string'},font:{type:'string'}}});
for(const key of ['source','browser','output'])if(!values[key])throw Error('--'+key+' is required');
const root=process.cwd(),out=path.resolve(values.output),source=path.resolve(values.source),executable=path.resolve(values.browser);
const relative=path.relative(path.join(root,'.goose/out'),out);if(!relative||relative.startsWith('..')||path.isAbsolute(relative))throw Error('Output must be a fresh owned .goose/out child');
const upstream='38a6a5c965aa99ab525161efb7cc5cf1fe62fced';
if(execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==upstream||execFileSync('git',['-C',source,'status','--porcelain','--untracked-files=no'],{encoding:'utf8'}).trim())throw Error('Source must be the clean pinned checkout');
fs.mkdirSync(out);fs.mkdirSync(path.join(out,'tmp'));process.env.TEMP=process.env.TMP=path.join(out,'tmp');
const assets=path.join(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm/assets');
const input=path.join(source,'packages/bundle/web-app/tests/fixtures/document-conversion.docx');
const routes=new Map(['dsoffice.cjs','dsoffice.wasm','dsoffice.data','dsoffice.data.js.metadata'].map(name=>[name,path.join(assets,name)]));routes.set('input.docx',input);routes.set('font.ttf',values.font?path.resolve(values.font):path.join(process.env.WINDIR||'C:/Windows','Fonts/arial.ttf'));
const manifest=JSON.parse(fs.readFileSync(path.join(assets,'../prebuilds.json'),'utf8')),inputs={};for(const [name,file]of routes){const bytes=fs.readFileSync(file),sha256=crypto.createHash('sha256').update(bytes).digest('hex');inputs[name]={size:bytes.length,sha256};if(name.startsWith('dsoffice.')&&manifest.files['assets/'+name]!==sha256)throw Error('Pinned engine asset mismatch: '+name);}
const requests=[];const server=http.createServer((req,res)=>{
 const name=new URL(req.url,'http://localhost').pathname.slice(1);requests.push(name);
 res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
 if(!name){res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>Owned conversion probe</title>');return;}
 const file=routes.get(name);if(!file){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',name.endsWith('.wasm')?'application/wasm':name.endsWith('.cjs')?'application/javascript':'application/octet-stream');res.setHeader('Content-Length',fs.statSync(file).size);fs.createReadStream(file).pipe(res);
});await new Promise(r=>server.listen(0,'127.0.0.1',r));
const {chromium}=await import(pathToFileURL(path.join(source,'node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs')).href);
let browser;const report={upstream,command:[process.execPath,...process.argv.slice(1)],inputs,scope:'Actual pinned WASM engine conversion in Chromium 108 worker. Arial-only controlled font collaborator; not font matching parity or Windows 7 execution.',requests,console:[]};
async function workerMain(base){
 const trace=[],fonts=[];let instance,office=0,document=0,payload;
 const error=()=>{
  const p=instance.ccall('dsh_lok_error','number',['number'],[office]);
  if(!p)return 'engine failure';try{return instance.UTF8ToString(p);}finally{instance.ccall('free',null,['number'],[p]);}
 };
 try{
  importScripts(base+'/dsoffice.cjs');
  const [data,font,input]=await Promise.all(['dsoffice.data','font.ttf','input.docx'].map(async name=>new Uint8Array(await(await fetch(base+'/'+name)).arrayBuffer())));
  instance=await createLibreOfficeModule({noInitialRun:true,mainScriptUrlOrBlob:base+'/dsoffice.cjs',locateFile:name=>base+'/'+name,getPreloadedPackage:()=>data.buffer,
   print:line=>trace.push(line),printErr:line=>trace.push(line),dshResolveSystemFonts:request=>{fonts.push(request);return ['/dsh-fonts/arial.ttf'];},
   preRun:[m=>{
    for(const name of ['/dsh/profile/user','/dsh/font-cache','/dsh-fonts'])m.FS.mkdirTree(name);
    m.FS.writeFile('/dsh-fonts/arial.ttf',font);
    m.FS.writeFile('/dsh/fonts.conf',new TextEncoder().encode('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>/dsh-fonts</dir><cachedir>/dsh/font-cache</cachedir></fontconfig>'));
    m.FS.writeFile('/dsh/profile/user/registrymodifications.xcu',new TextEncoder().encode('<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item><item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="ExperimentalMode" oor:op="fuse"><value>false</value></prop></item><item oor:path="/org.openoffice.VCL/FontSubstitutions/en"></item></oor:items>'));
    Object.assign(m.ENV,{HOME:'/dsh/profile',TMPDIR:'/tmp',FONTCONFIG_FILE:'/dsh/fonts.conf',LOK_HOST_ALLOWLIST:'^$'});
   }]});
  instance.FS.writeFile('/dsh/input.docx',input);
  office=instance.ccall('dsh_lok_initialize','number',['string','string'],['/instdir/program','file:///dsh/profile']);if(!office)throw Error(error());
  document=instance.ccall('dsh_lok_document_load','number',['number','string','string'],[office,'file:///dsh/input.docx','Batch=true,EnableMacrosExecution=false']);if(!document)throw Error(error());
  const files={};
  for(const format of ['pdf','txt']){
   const output='/dsh/output.'+format;
   const okay=instance.ccall('dsh_lok_document_export','number',['number','number','string','string','string','number','string'],[office,document,'file://'+output,format,format==='txt'?'UTF8,LF':'',0,'']);if(!okay)throw Error(error());
   files[format]=instance.FS.readFile(output);
  }
  const pdfBytes=files.pdf,bytesPointer=instance.ccall('malloc','number',['number'],[pdfBytes.length]);
  new Uint8Array(instance.HEAPU32.buffer,bytesPointer,pdfBytes.length).set(pdfBytes);
  const pdf=instance.ccall('dsh_pdf_open','number',['number','number','string'],[bytesPointer,pdfBytes.length,'']);
  instance.ccall('free',null,['number'],[bytesPointer]);if(!pdf)throw Error(error());
  try{
   const pageCount=instance.ccall('dsh_pdf_page_count','number',['number'],[pdf]);
   const dimensions=instance.ccall('malloc','number',['number'],[8]);
   if(!instance.ccall('dsh_pdf_page_size','number',['number','number','number','number'],[pdf,0,dimensions,dimensions+4]))throw Error(error());
   const pageWidth=instance.HEAPU32[dimensions/4],pageHeight=instance.HEAPU32[dimensions/4+1];instance.ccall('free',null,['number'],[dimensions]);
   const width=612,height=Math.round(width*pageHeight/pageWidth),pixels=instance.ccall('malloc','number',['number'],[width*height*4]);
   let rgba;
   try{
    if(!instance.ccall('dsh_pdf_paint','number',Array(9).fill('number'),[pdf,pixels,0,width,height,0,0,pageWidth,pageHeight]))throw Error(error());
    rgba=new Uint8ClampedArray(new Uint8Array(instance.HEAPU32.buffer,pixels,width*height*4));
   }finally{instance.ccall('free',null,['number'],[pixels]);}
   const canvas=new OffscreenCanvas(width,height);canvas.getContext('2d').putImageData(new ImageData(rgba,width,height),0,0);
   files.png=new Uint8Array(await(await canvas.convertToBlob({type:'image/png'})).arrayBuffer());
   let nonwhite=0;for(let i=0;i<rgba.length;i+=4)if(rgba[i]!==255||rgba[i+1]!==255||rgba[i+2]!==255)nonwhite++;if(!nonwhite)throw Error('Rendered page contains no visible content');
   trace.push({pageCount,width,height,pageWidth,pageHeight,nonwhite});
  }finally{instance.ccall('dsh_pdf_destroy','number',['number'],[pdf]);}
  if(!new TextDecoder().decode(files.txt).includes('Office preview ready'))throw Error('Exported text lost the original fixture content');
  payload={okay:true,files,fonts,trace};
 }catch(reason){payload={okay:false,error:reason.message,stack:reason.stack,fonts,trace};}
 finally{
  try{
   if(document){if(!instance.ccall('dsh_lok_document_destroy','number',['number'],[document]))throw Error(error());trace.push('document-destroyed');}
   if(office){if(!instance.ccall('dsh_lok_destroy','number',['number'],[office]))throw Error(error());trace.push('office-destroyed');}
  }catch(reason){payload={okay:false,error:'engine cleanup: '+reason.message,fonts,trace};}
  finally{if(instance){instance.PThread.terminateAllThreads();trace.push('pthreads-terminated');}}
 }
 self.postMessage(payload);
}
try{
 browser=await chromium.launch({executablePath:executable,headless:true,args:['--disable-gpu'],timeout:30000});report.browser=browser.version();if(report.browser!=='108.0.5359.0')throw Error('This probe freezes Chromium 108.0.5359.0');const page=await browser.newPage();
 page.on('console',msg=>report.console.push(msg.text().slice(0,500)));page.on('pageerror',e=>report.console.push(e.message));
 const base='http://127.0.0.1:'+server.address().port;await page.goto(base+'/');
 const result=await page.evaluate(async code=>await new Promise((resolve,reject)=>{
  const url=URL.createObjectURL(new Blob([code],{type:'application/javascript'})),worker=new Worker(url);
  const timer=setTimeout(()=>{worker.terminate();URL.revokeObjectURL(url);reject(Error('90-second conversion deadline'));},90000);
  worker.onmessage=event=>{clearTimeout(timer);worker.terminate();URL.revokeObjectURL(url);const result=event.data;
   if(result.files)for(const [format,bytes]of Object.entries(result.files))result.files[format]=Array.from(bytes);resolve(result);};
  worker.onerror=event=>{clearTimeout(timer);worker.terminate();URL.revokeObjectURL(url);reject(Error(event.message));};
 }), '('+workerMain.toString()+')('+JSON.stringify(base)+')');
 const {files,...details}=result;report.result=details;report.outputs={};
 if(files)for(const [format,bytes]of Object.entries(files)){
  const data=Buffer.from(bytes);fs.writeFileSync(path.join(out,'actual.'+format),data);report.outputs[format]={size:data.length,sha256:crypto.createHash('sha256').update(data).digest('hex')};
 }
 report.status=result.okay?'passed':'failed';
}catch(error){report.status='failed';report.error=error.message;}
finally{
 if(browser)await browser.close();await new Promise(r=>server.close(r));
 report.input={size:fs.statSync(input).size,sha256:crypto.createHash('sha256').update(fs.readFileSync(input)).digest('hex')};
 process.exitCode=report.status==='passed'?0:1;fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,error:report.error,result:report.result?{okay:report.result.okay,error:report.result.error,trace:report.result.trace,fontRequests:report.result.fonts.length}:null,outputs:report.outputs}));
}
