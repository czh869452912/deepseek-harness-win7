import {readFileSync} from 'node:fs'
import {mkdir,writeFile,readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Manager}=await load('packages/boot/plugin-manager/src/index.ts'),official=await load('packages/util/official-bundles/src/index.ts')
const input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const mode of input.cases){
 const ctx=new Context(),home=join(input.workspace,'source',mode),dir=join(home,'profile'),calls:any[]=[];await mkdir(dir,{recursive:true})
 const write=async(path:string,value:any)=>{await mkdir(join(path,'..'),{recursive:true});await writeFile(path,JSON.stringify(value))}
 async function pkg(name:string,extra:any={},root=dir){const location=join(root,'node_modules',name);await write(join(location,'package.json'),{name,version:'1.0.0',description:'Local '+name,dsh:{bundle:{patch:'cordis.patch.yml'}},...extra});await write(join(location,'cordis.patch.yml'),[{insert:[{id:name,name:'cordis:active'}]},{id:'foreign',disabled:true}]);return location}
 const anchor=join(home,'package.json');await write(anchor,{name:'installation',dependencies:mode==='shipped'?{extra:'1.0.0'}:{}})
 const core=await pkg('core');await write(join(core,'cordis.patch.yml'),[{insert:[{id:'manager',name:'@deepseek-ai/dsh-plugin-manager'}]}]);const extra=await pkg('extra'),selected=['core','extra'],dependencies:any={extra:'^1.0.0',ordinary:'1.0.0'}
 await write(join(dir,'node_modules/ordinary/package.json'),{name:'ordinary',version:'1.0.0'})
 if(mode==='shipped')await pkg('extra',{version:'9.0.0'},home)
 const manifest=JSON.parse(await readFile(join(extra,'package.json'),'utf8'))
 if(mode==='platform')manifest.dsh.bundle.platforms=['darwin']
 if(['incompatible','exempted'].includes(mode))manifest.engines={dsh:'>=99.0.0'}
 if(mode==='exempted')await write(join(dir,'compatibility.json'),{'extra@1.0.0':['0.2.2-rc.3']})
 if(mode==='invalid-listing')manifest.dsh.bundle.listedByDefault='false'
 if(mode==='null-version'){manifest.version=null;manifest.description=null}
 await write(join(extra,'package.json'),manifest)
 if(mode==='missing-selected')selected.push('missing')
 if(mode==='not-bundle')selected.push('ordinary')
 if(mode==='offered-installed'){const name=official.OFFICIAL_ON_DEMAND_CATALOG[0].packageName;await pkg(name);dependencies[name]='1.0.0'}
 if(mode==='source-forms')for(const [name,spec] of [['git-pinned','github:a/b#'+'a'.repeat(40)],['git-branch','github:a/b#main'],['alias','npm:other@1'],['local','file:../plugin'],['tag','latest']]){await pkg(name);dependencies[name]=spec}
 await write(join(dir,'package.json'),{name:'profile',dependencies,dsh:{profile:{bundles:selected}}});await write(join(dir,'cordis.patch.yml'),[])
 const profile={name:'test',dir,patchPath:join(dir,'cordis.patch.yml'),installAnchor:anchor,cwd:home,home,startedBundles:[...selected],overlays:[],telemetryDisabledEnv:undefined},entries=[{id:'include:extra',options:{id:'extra',name:'cordis:active'},parent:{tree:{ctx:{baseUrl:'file:///C:/live/'}}}}]
 const services:any={loader:{entries:()=>entries},profileContext:profile,pluginPackages:{metaOf:(name:string)=>({title:'row '+name}),packageOf:()=>undefined,refresh:async()=>{calls.push('refresh')}}}
 if(mode!=='startup')services.hmr={runExclusive:async(operation:any)=>operation(),reconcileProfile:async(required:any[])=>{calls.push({reload:[...required]});return {warnings:[],pending:[]}}}
 for(const [key,value] of Object.entries(services)){ctx.provide(key);ctx[key]=value}
 try{
  await ctx.plugin(Manager)
  if(['broken-patch','protected-broken'].includes(mode))await writeFile(join(mode==='broken-patch'?extra:core,'cordis.patch.yml'),'[invalid')
  const first=await ctx.pluginManager.listBundles(),steps:any[]=[]
  for(const [name,enabled] of [['extra',false],['extra',false],['extra',true],['core',false]]){const result=await ctx.pluginManager.setBundleEnabled(name,enabled);steps.push({result,selected:JSON.parse(await readFile(join(dir,'package.json'),'utf8')).dsh.profile.bundles})}
  const second=await ctx.pluginManager.listBundles()
  function normalize(value:any):any{
   if(Array.isArray(value))return value.map(normalize)
   if(value&&typeof value==='object'){const result:any=Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)]));if('diagnostic'in result)result.diagnostic=!!result.diagnostic;if(typeof result.error==='string'&&result.error!=='dsh.bundle.listedByDefault must be a boolean')result.error=!!result.error;return result}
   return typeof value==='string'?value.replaceAll(dir,'<profile>').replaceAll(home,'<home>'):value
  }
  rows.push(normalize({name:mode,first,steps,second,calls}))
 }finally{await ctx.fiber.dispose()}
}
const paths=['index.ts','bundles.ts','plugin-manager.ts','catalog.generated.ts'],inputs=Object.fromEntries(paths.map(path=>['packages/util/official-bundles/src/'+path,createHash('sha256').update(readFileSync(join(process.argv[2]!,'packages/util/official-bundles/src',path))).digest('hex')]))
console.log(JSON.stringify([{data:{upstream:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',inputs,optionalBundles:official.OPTIONAL_BUNDLES,protectedPlugins:[...official.PROTECTED_PLUGINS],catalog:official.OFFICIAL_ON_DEMAND_CATALOG}},...rows]))
