import {readFileSync} from 'node:fs'
import {mkdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {boot,readProfilePatches,getDshRuntimeVersion}=await load('packages/boot/app-boot/src/index.ts'),{default:Manager}=await load('packages/boot/plugin-manager/src/index.ts'),{default:Hmr}=await load('packages/boot/hmr/src/index.ts'),{default:Timer}=await load('vendor/timer/src/index.ts')
const input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),output:any[]=[]
for(const mode of input.cases){
 const home=join(input.workspace,'source',mode),dir=join(home,'profile')
 const write=async(path:string,value:any)=>{await mkdir(join(path,'..'),{recursive:true});await writeFile(path,JSON.stringify(value))}
 await write(join(home,'package.json'),{name:'installation'});await write(join(dir,'package.json'),{name:'profile',dsh:{profile:{bundles:['core','extra']}}})
 for(const [name,rows] of [['core',[{id:'manager',name:'cordis:manager'}]],['extra',[{id:'managed',name:'cordis:active'}]]] as const){
  const pkg=join(dir,'node_modules',name);await write(join(pkg,'package.json'),{name,version:'1.0.0',dsh:{bundle:{patch:'patch.yml'}},...name==='extra'?{engines:{dsh:'>=99.0.0'}}:{}});await write(join(pkg,'patch.yml'),[{insert:rows}])
 }
 await write(join(dir,'cordis.yml'),[]);await write(join(dir,'cordis.patch.yml'),[])
 const profile:any={name:'test',dir,patchPath:join(dir,'cordis.patch.yml'),installAnchor:join(home,'package.json'),cwd:home,home,startedBundles:['core','extra'],overlays:[],telemetryDisabledEnv:undefined}
 const ctx=await boot('test',join(dir,'cordis.yml'),readProfilePatches('test',profile),(ctx:any)=>{ctx.provide('profileContext',profile);ctx.provide('appReady',{onReady:(listener:any)=>{listener();return()=>{}}});ctx.loader.builtins.manager=Manager;ctx.loader.builtins.active=(owner:any)=>owner.provide('exemptionProbe',true)})
 const facts:any[]=[];ctx.on('plugin-manager/operation',(event:any)=>{facts.push(event)})
 try{
  if(mode!=='startup'){await ctx.plugin(Timer);await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0});await ctx.hmr.runExclusive(()=>{})}
  if(mode==='reload-failure')ctx.hmr.reconcileProfile=async()=>{throw new Error('reload failed')}
  if(mode==='damaged')await writeFile(join(dir,'compatibility.json'),'[invalid')
  const runtime=getDshRuntimeVersion();let actions:any[]=[['extra@1.0.0',runtime,true,undefined],['extra@1.0.0',runtime,true,true],['extra@1.0.0',runtime,true,true],['extra@1.0.0',runtime,false,undefined]]
  const variants:any={range:['extra@^1.0.0',runtime],whitespace:[' extra@1.0.0 ',runtime],credential:['https://user:secret@example.com/pkg',runtime],'runtime-range':['extra@1.0.0','^1.0.0'],scoped:['@scope/extra@2.0.0',runtime],'old-runtime':['extra@1.0.0','0.0.1'],alias:['npm:extra@1.0.0',runtime]}
  if(mode in variants){const [pkg,requested]=variants[mode];actions=[[pkg,requested,true,true],[pkg,requested,false,undefined]]}
  if(mode==='boolean-risk')actions=[['extra@1.0.0',runtime,true,1]]
  const steps:any[]=[]
  for(const [pkg,requested,enabled,risk] of actions){
   const result=await ctx.pluginManager.setVersionExemption(pkg,requested,enabled,risk);for(let i=0;i<15;i++)await Promise.resolve()
   if(result.error&&'diagnostic'in result.error)result.error.diagnostic=true
   const listing=ctx.pluginManager.listVersionExemptions();listing.warnings=listing.warnings.length
   steps.push({result,listing,active:ctx.get('exemptionProbe')===true,selection:JSON.parse(readFileSync(join(dir,'package.json'),'utf8')).dsh.profile.bundles})
  }
  output.push({name:mode,steps,facts:facts.map(({id,time,...rest})=>rest)})
 }finally{await ctx.fiber.dispose()}
}
console.log(JSON.stringify(output))
