/** Rebuild the pinned Office SDK browser-volume adapter (large WASM excluded). */
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync,existsSync,mkdirSync,readdirSync} from 'node:fs';
import {resolve,relative,dirname} from 'node:path';
const target='38a6a5c965aa99ab525161efb7cc5cf1fe62fced';
if(process.argv.length!==4)throw Error('usage: node scripts/build_office_browser.mjs <Source> <new-output>');
const source=resolve(process.argv[2]),output=resolve(process.argv[3]),root=process.cwd();
if(existsSync(output))throw Error('Output must be new.');
if(execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==target ||
 execFileSync('git',['-C',source,'status','--porcelain','--untracked-files=no'],{encoding:'utf8'}).trim())throw Error('Requires clean pinned Source.');
const pkg=resolve(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit@0.2.3/node_modules/@deepseek-ai/libreoffice-kit');
if(JSON.parse(readFileSync(resolve(pkg,'package.json'),'utf8')).version!=='0.2.3')throw Error('Unexpected Office SDK version.');
const require=createRequire(resolve('scripts/oracles/package.json')),{build}=require('esbuild');
const platform=resolve('scripts/native/office-browser/platform.js'),pnpm=resolve(source,'node_modules/.pnpm');
const alias=Object.fromEntries(['worker_threads','crypto','fs','os','path','module'].map(name=>['node:'+name,platform]));
Object.assign(alias,{'buffer':resolve(pnpm,'buffer@6.0.3/node_modules/buffer/index.js'),
 '@noble/hashes/sha256':resolve(pnpm,'@noble+hashes@1.8.0/node_modules/@noble/hashes/esm/sha256.js')});
const result=await build({entryPoints:['scripts/native/office-browser/entry.js'],bundle:true,platform:'browser',
 format:'iife',target:'chrome108',write:false,metafile:true,legalComments:'external',outfile:resolve(output,'worker.js'),alias,
 define:{'import.meta.url':'location.href'},
 plugins:[{name:'original-office-worker-body',setup(build){
  build.onResolve({filter:/^@office\/(snapshot|worker|defaults|output)$/},args=>({path:args.path.endsWith('snapshot')?'font-snapshot-worker.js':args.path.endsWith('output')?'index-output.js':args.path.endsWith('defaults')?'index.js':'worker.js',namespace:'office-original'}));
  build.onLoad({filter:/.*/,namespace:'office-original'},args=>{
   const path=resolve(pkg,'lib',args.path==='index-output.js'?'index.js':args.path),text=readFileSync(path,'utf8');
   if(args.path==='index.js'||args.path==='index-output.js'){
    if(args.path==='index-output.js'){
     const first=text.indexOf('const CODES ='),last=text.indexOf('//#endregion',first),start=text.indexOf('function validateOutput('),end=text.indexOf('//#region lib/types/runtime.js',start);
     if(first<0||last<first||start<0||end<start)throw Error('Original output markers differ.');
     return {contents:"import {Buffer} from 'buffer';\n"+text.slice(first,last)+'\n'+text.slice(start,end)+'\nexport {validateOutput,pdfPageCount};',loader:'js',resolveDir:dirname(path)};
    }
    const start=text.indexOf('const SANS_CJK_FAMILIES ='),end=text.indexOf('const FONT_COLLECTION_NAMES =');
    if(start<0||end<=start)throw Error('Original defaults markers differ.');
    return {contents:text.slice(start,end)+'\nexport {DEFAULT_LIMITS,FONT_FALLBACKS};',loader:'js',resolveDir:dirname(path)};
   }
   const marker='//#region lib/types/'+(args.path==='worker.js'?'worker.js':'font-snapshot-worker.js');
   const start=text.indexOf(marker),end=text.lastIndexOf('//#endregion');
   if(start<0||end<start)throw Error('Original worker markers differ.');
   return {contents:text.slice(0,start)+'\nexport async function run(){\n'+text.slice(start,end)+'\n}\n',loader:'js',resolveDir:dirname(path)};
  });
 }}]});
const hash=data=>createHash('sha256').update(data).digest('hex'),inputs={},resources={};
function track(path){inputs[relative(root,resolve(path)).replaceAll('\\','/')]=hash(readFileSync(path));}
mkdirSync(output,{recursive:true});
function copy(name,path){const data=readFileSync(path);writeFileSync(resolve(output,name),data);resources[name]=hash(data);track(path);}
for(const file of result.outputFiles){const name=file.path.endsWith('.LEGAL.txt')?'worker.LEGAL.txt':'worker.js';writeFileSync(resolve(output,name),file.contents);resources[name]=hash(file.contents);}
for(const name of ['worker.js','font-snapshot-worker.js','index.js'])copy('original-'+name,resolve(pkg,'lib',name));
const dependencies=new Set([pkg]),embeddedNotices=[],metadataNotices=[];
for(const path of Object.keys(result.metafile.inputs)){
 if(path.startsWith('office-original:'))continue;
 const absolute=resolve(path);if(!absolute.startsWith(source+'\\')&&!absolute.startsWith(source+'/')&&!absolute.startsWith(resolve('scripts/native/office-browser')+'\\')&&!absolute.startsWith(resolve('scripts/native/office-browser')+'/'))throw Error('Unowned input: '+path);
 track(path);
 const text=readFileSync(path,'utf8'),header=text.match(/^\s*(\/\*[\s\S]*?\*\/)/)?.[1];
 if(header&&/copyright|licen[cs]e/i.test(header))embeddedNotices.push(relative(source,absolute).replaceAll('\\','/')+'\n'+header);
 if(!path.includes('node_modules'))continue;
 let directory=dirname(absolute);while(!existsSync(resolve(directory,'package.json'))||!JSON.parse(readFileSync(resolve(directory,'package.json'),'utf8')).name)directory=dirname(directory);
 dependencies.add(directory);
}
for(const directory of dependencies){
 const pkg=JSON.parse(readFileSync(resolve(directory,'package.json'),'utf8'));track(resolve(directory,'package.json'));
 const licenses=readdirSync(directory).filter(name=>/^(license|licence|notice)(\.|$)/i.test(name));
 if(!licenses.length){
  const declarations={'dfa@1.2.0':'MIT','brotli@1.3.3':'MIT','fontkit@2.0.4':'MIT','saxes@6.0.0':'ISC'};
  if(declarations[pkg.name+'@'+pkg.version]!==pkg.license)throw Error('Missing license: '+pkg.name);
  // These exact published tarballs have no standalone license file. Preserve
  // the original MIT declaration and author notice instead of inventing one.
  copy(pkg.name+'-PACKAGE-LICENSE.json',resolve(directory,'package.json'));
  metadataNotices.push({package:pkg.name+'@'+pkg.version,license:pkg.license,notice:pkg.name+'-PACKAGE-LICENSE.json'});
 }
 for(const license of licenses)copy(pkg.name.replaceAll('/','+')+'-'+license,resolve(directory,license));
}
const notices=embeddedNotices.join('\n\n')+'\n';writeFileSync(resolve(output,'upstream-notices.txt'),notices);resources['upstream-notices.txt']=hash(notices);
for(const path of ['scripts/build_office_browser.mjs',require.resolve('esbuild/package.json'),require.resolve('esbuild'),resolve('scripts/oracles/node_modules/@esbuild/win32-x64/esbuild.exe')])track(path);
writeFileSync(resolve(output,'manifest.json'),JSON.stringify({format:'dsh-office-browser@1',target_upstream:target,sdk:'@deepseek-ai/libreoffice-kit@0.2.3',
 node:process.version,esbuild:require('esbuild').version,transformation:'Original worker entry bodies wrapped in exported async run; platform imports bind an explicit physical-file memory volume and host directory/Dirent inventory. Original Office font discovery, filtering, locale sorting and deduplication execute unchanged. Browser fontkit and synchronous SHA-256. Physical metadata cache and public SDK orchestration are host responsibilities.',
 metadata_notices:metadataNotices,build_inputs:inputs,resources},null,2)+'\n');
console.log(JSON.stringify({output,resources,inputs:Object.keys(inputs).length}));
