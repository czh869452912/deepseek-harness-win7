import fs from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
import {pathToFileURL} from 'node:url'
import {join} from 'node:path'
const S=(await load('vendor/schemastery/src/index.ts')).default,{queryLiveConfig}=await load('packages/extensions/tool-cordis/src/config.ts')
const cases=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows=[]
for(const entry of cases){
 const calls:any[]=[],parent={tree:{ctx:{baseUrl:entry.noBase?undefined:'file:///fixture/'}}},schema=S.object({port:S.number().default(80).description('Listen port.')})
 const entries=['group','include','unloaded','disposed','disabled','absent','foreign','schema','failed','same','group:child','no-package'].map(id=>{
  const name=['schema','same','failed','group:child','no-package'].includes(id)?'with-schema':id
  const Config=name==='with-schema'?schema:id==='foreign'?{foreign:true}:undefined
  return {id,options:{id:id.split(':').at(-1),name},parent,subgroup:id==='group'?{}:undefined,subtree:id==='include'?{}:undefined,
   fiber:id==='unloaded'?undefined:{uid:id==='disposed'?null:0,runtime:{Config}},disabled:id==='disabled'}
 })
 const loader={entries:()=>entries.values(),resolve:(id:string)=>entries.find(row=>row.id===id)},packages={packageOf:(name:string,base:string)=>{
  calls.push([name,base]);if(entry.lookupError)throw Error('package lookup failed');return name==='absent'?undefined:{dir:'/fixture/packages/'+name}
 }}
 const ctx={get:(key:string)=>key==='loader'?entry.noLoader?undefined:loader:key==='pluginPackages'?entry.noPackages?undefined:packages:undefined}
 const node=entries.find(row=>row.id==='schema')!
 if(entry.mutation==='dispose')node.fiber!.uid=null
 if(entry.mutation==='disable')node.disabled=true
 if(entry.mutation==='remove-config')node.fiber!.runtime.Config=undefined
 if(entry.mutation==='replace-config')node.fiber!.runtime.Config=S.string().required()
 const input=entry.special?{[entry.special==='nan-limit'?'limit':'offset']:entry.special==='infinite-offset'?Infinity:NaN}:entry.input
 const row:any={case:entry,calls}
 try{row.value=await queryLiveConfig(ctx as any,input)}catch(error:any){row.error=error.message}
 rows.push(row)
}
if(process.argv[4]){
 const {base}=JSON.parse(await fs.readFile(process.argv[4],'utf8')),{Context}=await load('vendor/cordis/src/index.ts')
 const {PluginPackages}=await load('packages/boot/app-boot/src/profile-resolution/service.ts'),ctx=new Context()
 try{
  await ctx.plugin(PluginPackages)
  const bases=[pathToFileURL(base).href+'/',pathToFileURL(join(base,'caller.js')).href,pathToFileURL(base).href,pathToFileURL(base).href+'/?q=1#hash']
  for(const [index,parent] of bases.entries())for(const name of ['dsh-config-contract-dep/private','@scope/dsh-config-contract-dep']){
   rows.push({packageLookup:{base:index,name},value:ctx.pluginPackages.packageOf(name,parent)??null})
  }
 }finally{await ctx.fiber.dispose()}
}
console.log(JSON.stringify(rows))
