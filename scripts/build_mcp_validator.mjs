/** Carry the pinned SDK's unchanged default JSON Schema provider to Win7. */
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'
import {createRequire} from 'node:module'
import {readFileSync,writeFileSync,existsSync,mkdirSync,readdirSync} from 'node:fs'
import {resolve,relative,dirname} from 'node:path'
const target='38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
if(process.argv.length!==4)throw Error('usage: node scripts/build_mcp_validator.mjs <Source> <new-output>')
const source=resolve(process.argv[2]),output=resolve(process.argv[3]),root=process.cwd()
if(existsSync(output))throw Error('output must be new')
if(execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==target||execFileSync('git',['-C',source,'status','--porcelain','--untracked-files=no'],{encoding:'utf8'}).trim())throw Error('requires unchanged fixed Source')
const require=createRequire(resolve('scripts/oracles/package.json')),sdkRequire=createRequire(resolve(source,'packages/mcp/mcp-client/package.json'))
const entry=sdkRequire.resolve('@modelcontextprotocol/client/validators/ajv').replace(/\.cjs$/,'.mjs')
const {build}=require('esbuild')
const result=await build({entryPoints:['scripts/native/mcp-validator/entry.ts'],bundle:true,platform:'neutral',format:'iife',globalName:'__mcpValidator',target:'es2022',write:false,metafile:true,legalComments:'external',outfile:resolve(output,'validator.js'),alias:{'@sdk/validator':entry}})
mkdirSync(output,{recursive:true})
const hash=bytes=>createHash('sha256').update(bytes).digest('hex'),inputs={},resources={}
const track=path=>{inputs[relative(root,resolve(path)).replaceAll('\\','/')]=hash(readFileSync(path))}
const copy=(name,path)=>{const bytes=readFileSync(path);track(path);writeFileSync(resolve(output,name),bytes);resources[name]=hash(bytes)}
for(const file of result.outputFiles){const name=relative(output,file.path);writeFileSync(file.path,file.contents);resources[name]=hash(file.contents)}
copy('driver.js','scripts/native/mcp-validator/driver.js')
const dependencies=new Set()
for(const path of Object.keys(result.metafile.inputs)){
 track(path)
 if(!path.includes('node_modules'))continue
 let directory=dirname(resolve(path));while(!existsSync(resolve(directory,'package.json')))directory=dirname(directory)
 dependencies.add(directory)
 // The SDK distribution embeds its pure validator dependencies. Retain the
 // original package licenses as well as the SDK license and bundle notices.
 const content=readFileSync(path,'utf8')
 const licenses=JSON.parse(readFileSync('scripts/native/mcp-validator/licenses/inputs.json','utf8'))
 for(const match of content.matchAll(/#region \.\.\/\.\.\/node_modules\/\.pnpm\/([^/]+)\/node_modules\/((?:@[^/]+\/)?[^/]+)\//g)){
  const record=licenses.find(row=>row.name===match[2]&&match[1].startsWith(row.name+'@'+row.version))
  if(!record)throw Error('missing embedded dependency license '+match[1])
  const file=resolve('scripts/native/mcp-validator/licenses',record.name+'-LICENSE')
  if(hash(readFileSync(file))!==record.license_sha256)throw Error('embedded license bytes differ')
  copy(record.name+'-LICENSE',file)
 }
}
for(const directory of dependencies){
 const pkg=JSON.parse(readFileSync(resolve(directory,'package.json'),'utf8'));track(resolve(directory,'package.json'))
 const licenses=readdirSync(directory).filter(name=>/^(license|licence|notice)(\.|$)/i.test(name));if(!licenses.length)throw Error('missing license '+pkg.name)
 for(const license of licenses)copy(pkg.name.replaceAll('/','+')+'-'+license,resolve(directory,license))
}
for(const path of ['scripts/build_mcp_validator.mjs',require.resolve('esbuild/package.json'),require.resolve('esbuild'),resolve('scripts/oracles/node_modules/@esbuild/win32-x64/esbuild.exe')])track(path)
copy('license-inputs.json','scripts/native/mcp-validator/licenses/inputs.json')
writeFileSync(resolve(output,'manifest.json'),JSON.stringify({format:'dsh-mcp-validator@1',target_upstream:target,engine:'shipped Win7 QuickJS',node:process.version,esbuild:require('esbuild').version,build_inputs:inputs,resources},null,2)+'\n')
console.log(JSON.stringify({output,resources}))
