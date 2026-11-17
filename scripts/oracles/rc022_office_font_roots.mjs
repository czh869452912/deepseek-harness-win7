/** Exercise the actual pinned SDK systemFontDirectories function body. */
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';import {execFileSync} from 'node:child_process';
const source=path.resolve(process.argv[2]);
if(execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!=='38a6a5c965aa99ab525161efb7cc5cf1fe62fced' ||
 execFileSync('git',['-C',source,'status','--porcelain','--untracked-files=no'],{encoding:'utf8'}).trim())throw Error('Requires clean pinned Source.');
const text=fs.readFileSync(path.join(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit@0.2.3/node_modules/@deepseek-ai/libreoffice-kit/lib/index.js'),'utf8');
const start=text.indexOf('function systemFontDirectories('),end=text.indexOf('//#endregion',start);
if(start<0||end<start)throw Error('Font directory markers differ.');
const roots=vm.runInNewContext(text.slice(start,end)+'\nsystemFontDirectories',{win32:path.win32,posix:path.posix,join:path.join,readdirSync:fs.readdirSync,absent:error=>['ENOENT','EACCES','EPERM','ENOTDIR'].includes(error.code)});
const rows=JSON.parse(fs.readFileSync(0,'utf8')).map(request=>({request,roots:roots(request.platform,request.home,request.env)}));
console.log(JSON.stringify(rows));
