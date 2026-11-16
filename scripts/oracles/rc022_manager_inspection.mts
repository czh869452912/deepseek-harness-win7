import {readFileSync} from 'node:fs'
import {mkdir,writeFile,readFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {boot,readProfilePatches}=await load('packages/boot/app-boot/src/index.ts'),{default:Manager}=await load('packages/boot/plugin-manager/src/index.ts'),{remoteMethods}=await load('packages/typert/protocol/src/index.ts')
const data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),output:any[]=[]
async function write(path:string,value:any){await mkdir(join(path,'..'),{recursive:true});await writeFile(path,JSON.stringify(value))}
function normalize(value:any):any{
 if(Array.isArray(value))return value.map(normalize)
 if(value===null||typeof value!=='object')return value
 const result:any=Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)]))
 if(typeof result.reason==='string'){
  if(result.reason.startsWith('no readable package.json at the path:'))result.reason='no readable package.json at the path: <reader diagnostic>'
  if(result.reason.startsWith('unreadable pnpm view output:'))result.reason='unreadable pnpm view output: <parser diagnostic>'
 }
 return result
}
for(const item of data.cases){
 const home=join(data.workspace,'source',item.name),dir=join(home,'profile');await mkdir(dir,{recursive:true})
 await write(join(home,'package.json'),{name:'installation',dependencies:{shipped:'1.0.0'}})
 await write(join(dir,'package.json'),{name:'profile',dependencies:{installed:item.source??'^1.0.0'},dsh:{profile:{bundles:['core','installed']}}})
 for(const name of ['core','installed']){
  const pkg=join(dir,'node_modules',name)
  await write(join(pkg,'package.json'),{name,version:'1.0.0',dsh:{bundle:{patch:'patch.yml'}}})
  await write(join(pkg,'patch.yml'),name==='core'?[{insert:[{id:'manager',name:'cordis:manager',config:item.config??{}}]}]:[])
 }
 await write(join(dir,'cordis.yml'),[]);await write(join(dir,'cordis.patch.yml'),[]);await write(join(dir,'query.json'),item.query)
 const script=join(dir,'package.py');await writeFile(script,data.program)
 let argument=item.argument
 if(argument==='<local>'){
  const local=join(home,'local'),kind=item.local;argument=local
  if(kind!=='missing'){
   await mkdir(local);const manifest:any={name:'local',version:'1.2.3',description:'local bundle',dsh:{bundle:kind==='array'?[]:{}}}
   if(kind==='no-name')delete manifest.name
   if(kind==='no-bundle')delete manifest.dsh
   if(kind==='known')manifest.name='installed'
   if(kind!=='unreadable')await write(join(local,'package.json'),manifest)
   if(kind==='broken')await writeFile(join(local,'package.json'),'{')
  }
 }
 if(argument==='<tar>')argument=join(home,'missing.tgz')
 if(item.exemption)await write(join(dir,'compatibility.json'),{})
 const profile:any={name:'test',dir,patchPath:join(dir,'cordis.patch.yml'),installAnchor:join(home,'package.json'),cwd:home,home,startedBundles:['core','installed'],overlays:[],packageManager:{command:data.python,args:[script]}}
 const ctx=await boot('test',join(dir,'cordis.yml'),readProfilePatches('test',profile),(ctx:any)=>{ctx.provide('profileContext',profile);ctx.loader.builtins.manager=Manager})
 try{
  const manager=ctx.pluginManager
  if(item.exemption)await manager.setVersionExemption('installed@4.0.0','0.2.2-rc.3',true,true)
  if(item.origin)manager.installedFrom.set('installed',item.origin)
  const controller=new AbortController();let timer:any
  if(item.cancel==='pre')controller.abort()
  if(item.cancel==='later')timer=setTimeout(()=>controller.abort(),500)
  let result:any
  try{result=await manager[item.method](...item.method==='registries'?[]:[argument,item.options,controller.signal])}finally{if(timer)clearTimeout(timer)}
  let queries:any[]=[]
  try{queries=(await readFile(join(dir,'queries.jsonl'),'utf8')).trim().split('\n').filter(Boolean).map(line=>JSON.parse(line))}catch{}
  queries.sort((a,b)=>a.spec.localeCompare(b.spec)||(a.registry??'').localeCompare(b.registry??''))
  output.push({name:item.name,result:normalize(result),queries,remote:['registries','inspect','listVersions'].every(name=>remoteMethods(manager).some((row:any)=>row.method===name))})
 }finally{await ctx.fiber.dispose()}
}
console.log(JSON.stringify(output))
