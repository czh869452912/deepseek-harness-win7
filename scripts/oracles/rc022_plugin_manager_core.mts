import {readFileSync,existsSync,unlinkSync} from 'node:fs'
import {mkdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {boot,readProfilePatches}=await load('packages/boot/app-boot/src/index.ts'),{default:Manager}=await load('packages/boot/plugin-manager/src/index.ts'),{default:Hmr}=await load('packages/boot/hmr/src/index.ts'),{default:Timer}=await load('vendor/timer/src/index.ts')
const input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),output:any[]=[]
for(const mode of input.cases){
 const home=join(input.workspace,'source',mode),dir=join(home,'profile'),bundle=join(dir,'node_modules/core');await mkdir(bundle,{recursive:true})
 const write=(path:string,value:any)=>writeFile(path,JSON.stringify(value))
 await write(join(home,'package.json'),{name:'installation'});await write(join(dir,'package.json'),{name:'profile',dsh:{profile:{bundles:['core']}}});await write(join(bundle,'package.json'),{name:'core',version:'1.0.0',dsh:{bundle:{patch:'cordis.patch.yml'}}});await write(join(bundle,'cordis.patch.yml'),[{insert:[{id:'manager',name:'cordis:manager',config:{lockWaitMs:0}},{id:'managed',name:'cordis:active'}]}]);await write(join(dir,'cordis.yml'),[]);await write(join(dir,'cordis.patch.yml'),[])
 const profile:any={name:'test',dir,patchPath:join(dir,'cordis.patch.yml'),installAnchor:join(home,'package.json'),cwd:home,home,startedBundles:['core'],overlays:mode==='overlay'?[{id:'managed',disabled:true}]:[],telemetryDisabledEnv:undefined}
 const ctx=await boot('test',join(dir,'cordis.yml'),readProfilePatches('test',profile),(ctx:any)=>{ctx.provide('profileContext',profile);ctx.provide('appReady',{onReady:(listener:any)=>{listener();return()=>{}}});ctx.loader.builtins.manager=Manager;ctx.loader.builtins.active=(owner:any)=>owner.provide('managedProbe',true)})
 const operations:any[]=[],changed:any[]=[],identities:string[]=[];ctx.on('plugin-manager/operation',(event:any)=>operations.push(event));ctx.on('plugin-manager/changed',(event:any)=>changed.push(event));const drain=async()=>{for(let i=0;i<15;i++)await new Promise(resolve=>setImmediate(resolve))}
 try{
  const manager=ctx.pluginManager
  if(mode==='diagnostic-failure')ctx.on('plugin-manager/operation',()=>{throw Error('diagnostic unavailable')})
  if(mode!=='startup'){await ctx.plugin(Timer);await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0});await ctx.hmr.runExclusive(async()=>{})}
  if(mode==='foreign')await ctx.loader.create({id:'foreign',name:'cordis:active'})
  const initial=await manager.listPlugins(),steps:any[]=[]
  if(mode==='pending')ctx.hmr.reconcileProfile=async()=>({warnings:['existing inactive'],pending:[{reason:'host-module'}]})
  if(mode==='reload-error')ctx.hmr.reconcileProfile=async()=>{throw Error('reload failed')}
  if(mode==='unloaded')await ctx.loader.resolve('include:manager').fiber.dispose()
  const lock=join(dir,'package.json.lock');if(mode==='lock-error')await writeFile(lock,'owned test lock')
  try{
   const actions:any[]=[['include:managed',false],['include:managed',false],['include:managed',true],['include:manager',false],['missing',true]];if(mode==='foreign')actions.push(['foreign',false])
   for(const [identity,enabled] of actions){let result;try{result=await manager.setPluginEnabled(identity,enabled)}catch{result={threw:true}}await drain();const rows=mode==='unloaded'?[]:await manager.listPlugins();steps.push({result,managed:rows.find((row:any)=>row.entryId==='include:managed')??null})}
  }finally{if(existsSync(lock))unlinkSync(lock)}
  await drain();const facts=operations.map(event=>{if(!identities.includes(event.id))identities.push(event.id);const {id,time,...rest}=event;return {...rest,operation:identities.indexOf(id),validTime:/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(time)}})
  output.push({name:mode,initial,steps,changed,facts,lockReleased:!existsSync(lock)})
 }finally{await ctx.fiber.dispose()}
}
console.log(JSON.stringify(output))
