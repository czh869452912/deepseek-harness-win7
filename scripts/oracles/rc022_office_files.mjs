/** Run the pinned public SDK's pre-worker file ownership paths and readBounded. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const source=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);
if(execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!=='38a6a5c965aa99ab525161efb7cc5cf1fe62fced' ||
 execFileSync('git',['-C',source,'status','--porcelain','--untracked-files=no'],{encoding:'utf8'}).trim())throw Error('Requires clean pinned Source.');
fs.mkdirSync(out);
const pkg=path.join(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit@0.2.3/node_modules/@deepseek-ai/libreoffice-kit');
const wasm=path.join(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm/package.json');
const sdk=await import(pathToFileURL(path.join(pkg,'lib/index.js')));
const converter=await sdk.createConverter({fontDirectories:[],fontMetadataCacheDirectory:false,maxInputBytes:4,
 resolveEnginePackage(name){if(name.endsWith('-wasm'))return wasm;const error=Error('Not selected');error.code='MODULE_NOT_FOUND';throw error;}});
const rows=[];
function outcome(error){return error instanceof sdk.ConversionError?{code:error.code,message:error.message}:{os:true};}
try{
 for(const name of ['empty','oversized','missing-input','existing-output','output-directory','missing-output-parent','existing-output-missing-input','aborted']){
  const run=path.join(out,name);fs.mkdirSync(run);
  const input=path.join(run,'input.docx'),output=name==='missing-output-parent'?path.join(run,'missing/output.txt'):path.join(run,'output.txt');
  if(!name.includes('missing-input'))fs.writeFileSync(input,name==='empty'?'':name==='oversized'?'12345':'123');
  if(name.includes('existing-output'))fs.writeFileSync(output,'KEEP');
  if(name==='output-directory')fs.mkdirSync(output);
  const controller=new AbortController();if(name==='aborted')controller.abort('raw abort');
  let result;
  try{await converter.convert({inputPath:input,outputPath:output},controller.signal);result={unexpected:true};}
  catch(error){result=error==='raw abort'?{abort:'raw abort'}:outcome(error);}
  rows.push({name,result,output:fs.existsSync(output)?fs.statSync(output).isDirectory()?'directory':fs.readFileSync(output,'utf8'):null});
 }
 const text=fs.readFileSync(path.join(pkg,'lib/index.js'),'utf8');
 const start=text.indexOf('const CHANGED_KEYS ='),end=text.indexOf('async function runWorker(',start);
 if(start<0||end<start)throw Error('Bounded read markers differ.');
 const read=vm.runInNewContext(text.slice(start,end)+'\nreadBounded',{open:fs.promises.open,constants:fs.constants,ConversionError:sdk.ConversionError,Buffer});
 for(const [name,contents,limit,role] of [['read-exact','1234',4,'input'],['read-empty-output','',4,'output'],['read-empty-input','',4,'input'],['read-output-limit','12345',4,'output']]){
  const file=path.join(out,name);fs.writeFileSync(file,contents);let result;
  try{result={text:(await read(file,limit,new AbortController().signal,role)).toString()};}catch(error){result=outcome(error);}
  rows.push({name,result});
 }
}finally{await converter.dispose();}
fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({rows},null,2));
console.log(JSON.stringify({rows}));
