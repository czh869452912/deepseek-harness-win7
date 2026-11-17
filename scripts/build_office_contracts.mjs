/** Preserve original SDK pure validation bodies on the shipped Win7 engine. */
import {createHash} from 'node:crypto';import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync,existsSync,mkdirSync} from 'node:fs';import {resolve,relative} from 'node:path';
const target='38a6a5c965aa99ab525161efb7cc5cf1fe62fced';
if(process.argv.length!==4)throw Error('usage: node scripts/build_office_contracts.mjs <Source> <new-output>');
const source=resolve(process.argv[2]),output=resolve(process.argv[3]),root=process.cwd();
if(existsSync(output))throw Error('Output must be new.');
if(execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==target ||
 execFileSync('git',['-C',source,'status','--porcelain','--untracked-files=no'],{encoding:'utf8'}).trim())throw Error('Requires clean pinned Source.');
const pkg=resolve(source,'node_modules/.pnpm/@deepseek-ai+libreoffice-kit@0.2.3/node_modules/@deepseek-ai/libreoffice-kit');
const file=resolve(pkg,'lib/index.js'),text=readFileSync(file,'utf8'),hash=data=>createHash('sha256').update(data).digest('hex'),regions=[];
function section(start,end){const first=text.indexOf(start),last=text.indexOf(end,first+start.length);if(first<0||last<=first)throw Error('Source section differs: '+start);regions.push({start,end,sha256:hash(text.slice(first,last))});return text.slice(first,last);}
const code=[section('const CODES =','//#endregion'),section('const MAX_COLUMN =','function sheetPartInfo('),
 section('const IMAGE_FORMATS =','function selectedPages('),section('const SANS_CJK_FAMILIES =','//#endregion'),
 section('const CONVERSION_FORMATS =','/**\n* Reject an engine output')].join('\n');
const inputs={},resources={};mkdirSync(output,{recursive:true});
function track(path){inputs[relative(root,resolve(path)).replaceAll('\\','/')]=hash(readFileSync(path));}
function write(name,bytes){writeFileSync(resolve(output,name),bytes);resources[name]=hash(bytes);}
function copy(name,path){write(name,readFileSync(path));track(path);}
track(file);write('contracts.js',code+'\n');
copy('driver.js','scripts/native/office-browser/contracts-driver.js');
for(const name of ['LICENSE','NOTICE'])copy('SDK-'+name,resolve(pkg,name));
track('scripts/build_office_contracts.mjs');
writeFileSync(resolve(output,'manifest.json'),JSON.stringify({format:'dsh-office-contracts@1',target_upstream:target,sdk:'@deepseek-ai/libreoffice-kit@0.2.3',
 engine:'shipped Win7 QuickJS',transformation:'Verbatim pure SDK validation sections; driver supplies only closed host path queries and system roots.',regions,build_inputs:inputs,resources},null,2)+'\n');
console.log(JSON.stringify({output,resources}));
