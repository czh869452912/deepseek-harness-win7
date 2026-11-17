/** Evaluate original SDK validation bodies with actual Node path/OS providers. */
import fs from 'node:fs';import path from 'node:path';import os from 'node:os';import vm from 'node:vm';import {execFileSync} from 'node:child_process';
const source=path.resolve(process.argv[2]);
if(execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!=='38a6a5c965aa99ab525161efb7cc5cf1fe62fced' ||
 execFileSync('git',['-C',source,'status','--porcelain','--untracked-files=no'],{encoding:'utf8'}).trim())throw Error('Requires clean pinned Source.');
const text=fs.readFileSync(path.join(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit@0.2.3/node_modules/@deepseek-ai/libreoffice-kit/lib/index.js'),'utf8');
function section(start,end){const first=text.indexOf(start),last=text.indexOf(end,first+start.length);if(first<0||last<=first)throw Error('Original markers differ.');return text.slice(first,last);}
const code=[section('const CODES =','//#endregion'),section('const MAX_COLUMN =','function sheetPartInfo('),section('const IMAGE_FORMATS =','function selectedPages('),
 section('function systemFontDirectories(','//#endregion'),section('function defaultFontMetadataCacheDirectory(','//#endregion'),section('const SANS_CJK_FAMILIES =','//#endregion'),
 section('const CONVERSION_FORMATS =','/**\n* Reject an engine output')].join('\n');
const observe=vm.runInNewContext(code+'\n((kind,value)=>kind==="options"?resolveOptions(value):kind==="images"?resolveImageRender(value):resolveConversion(value,kind))',
 {...path,homedir:os.homedir,process,readdirSync:fs.readdirSync,absent:error=>['ENOENT','EACCES','EPERM','ENOTDIR'].includes(error.code)});
const rows=[];
for(const request of JSON.parse(fs.readFileSync(0,'utf8'))){
 for(const special of request.specials){let parent=request;for(const key of special.path.slice(0,-1))parent=parent[key];parent[special.path.at(-1)]=special.kind==='nan'?NaN:special.kind==='positive'?Infinity:special.kind==='negative'?-Infinity:undefined;}
 try{rows.push({ok:true,value:observe(request.kind,request.value)});}catch(error){rows.push({ok:false,name:error.name,message:error.message,...error.code===undefined?{}:{code:error.code}});}
}
console.log(JSON.stringify(rows));
