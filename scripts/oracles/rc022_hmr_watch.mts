import {mkdirSync,readFileSync,writeFileSync,unlinkSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source')
const settleBeforeExit=JSON.parse(readFileSync(process.argv[3]!,'utf8')).settleBeforeExit!==false
const {boot,readProfilePatches}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/index.ts')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/src/index.ts')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
mkdirSync(directory,{recursive:true});const result:any[]=[]
const sleep=(ms:number)=>new Promise<void>(done=>setTimeout(done,ms))
const until=async(condition:()=>boolean)=>{for(let index=0;index<1000;index++){if(condition())return;await sleep(10)}throw new Error('profile watcher did not converge')}
for(const mode of ['commit','cancel']){
 const owner=join(directory,mode),profile=join(owner,'profile');mkdirSync(profile,{recursive:true})
 const rootConfig=join(profile,'cordis.yml'),manifest=join(profile,'package.json'),patch=join(profile,'cordis.patch.yml'),homePatch=join(owner,'cordis.patch.yml')
 writeFileSync(rootConfig,'[]');const manifestValue:any={name:'test',dsh:{profile:{bundles:[]}}};writeFileSync(manifest,JSON.stringify(manifestValue))
 const rows:any[]=[{insert:[{id:'timer',name:'cordis:timer'},{id:'hmr',name:'cordis:hmr',config:{root:[],awaitWriteFinish:{stabilityThreshold:20,pollInterval:10}}},{id:'probe',name:'cordis:probe',config:{value:'initial'}}]}];writeFileSync(patch,JSON.stringify(rows))
 const context:any={dir:profile,home:owner,patchPath:patch,startedBundles:[],installAnchor:join(owner,'package.json'),overlays:[],telemetryDisabledEnv:undefined}
 let ready=false;const listeners=new Set<()=>void>(),events:string[]=[]
 const commit=()=>{ready=true;for(const listener of listeners)listener();listeners.clear()}
 const ctx=await boot('test',rootConfig,readProfilePatches('test',context),(host:any)=>{
  host.provide('profileContext',context);host.provide('appReady',{onReady(listener:()=>void){if(ready){listener();return()=>{}}listeners.add(listener);return()=>{listeners.delete(listener)}}})
  host.loader.builtins.timer=Timer;host.loader.builtins.hmr=Hmr;host.loader.builtins.probe=(owner:any,config:any)=>{owner.provide('probeValue',config.value)}
  host.on('app-boot/config-reload',()=>{events.push('reload')})
 })
 const hmr:any=ctx.hmr
 try{
  rows[0].insert.at(-1).config.value='edited-before-ready';writeFileSync(patch,JSON.stringify(rows));const before=ctx.get('probeValue')
  if(mode==='cancel'){await ctx.fiber.dispose();commit?.();result.push({mode,before,value:ctx.get('probeValue')??null,active:ctx.get('hmr')!==undefined});continue}
  commit?.();await until(()=>ctx.get('probeValue')==='edited-before-ready');await hmr.runExclusive(async()=>{});result.push({step:'ready',before,value:ctx.get('probeValue')})
  writeFileSync(homePatch,JSON.stringify([{id:'probe',config:{value:'home'}}]));await until(()=>ctx.get('probeValue')==='home');await hmr.runExclusive(async()=>{});result.push({step:'home',value:ctx.get('probeValue')});await sleep(150)
  unlinkSync(homePatch);await until(()=>ctx.get('probeValue')==='edited-before-ready');await hmr.runExclusive(async()=>{});result.push({step:'home-unlink',value:ctx.get('probeValue')})
  let count=events.length;manifestValue.dependencies={unselected:'1.0.0'};writeFileSync(manifest,JSON.stringify(manifestValue));await sleep(200);await hmr.runExclusive(async()=>{});result.push({step:'dependencies-only',reloaded:events.length!==count})
  const bundle=join(profile,'node_modules/added');mkdirSync(bundle,{recursive:true});writeFileSync(join(bundle,'package.json'),JSON.stringify({name:'added',dsh:{bundle:{patch:'./patch.json'}}}));writeFileSync(join(bundle,'patch.json'),JSON.stringify([{insert:[{id:'bundled',name:'cordis:probe',disabled:true}]}]))
  manifestValue.dsh.profile.bundles=['added'];writeFileSync(manifest,JSON.stringify(manifestValue));await until(()=>[...ctx.loader.entries()].some((entry:any)=>entry.options.id==='bundled'));await hmr.runExclusive(async()=>{});count=events.length;result.push({step:'bundles',bundled:true,value:ctx.get('probeValue')})
  writeFileSync(patch,JSON.stringify(rows)+'\n');await until(()=>events.length>count);await hmr.runExclusive(async()=>{});count=events.length;writeFileSync(patch,JSON.stringify(rows)+'\n');await sleep(200);await hmr.runExclusive(async()=>{});result.push({step:'unchanged-inputs',reloaded:events.length!==count})
  rows[0].insert[1].config={root:[],debounce:1,awaitWriteFinish:{stabilityThreshold:20,pollInterval:10}};writeFileSync(patch,JSON.stringify(rows));await until(()=>ctx.get('hmr')!==undefined&&(ctx.hmr as any).executing!==hmr.executing)
  rows[0].insert.at(-1).config.value='after-hmr-replacement';writeFileSync(patch,JSON.stringify(rows));await until(()=>ctx.get('probeValue')==='after-hmr-replacement');if(settleBeforeExit)await ctx.hmr.runExclusive(async()=>{});result.push({step:'provider-replacement',old_active:!hmr.closing,value:ctx.get('probeValue')})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
