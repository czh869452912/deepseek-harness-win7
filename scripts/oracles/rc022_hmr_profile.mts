import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve,basename} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!,directory=resolve(dirname(input),'files/source')
const {boot}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/index.ts')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/src/index.ts')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
mkdirSync(directory,{recursive:true});const result:any[]=[]
for(const mode of JSON.parse(readFileSync(input,'utf8'))){
 const owner=join(directory,mode),profile=join(owner,'profile');mkdirSync(profile,{recursive:true})
 writeFileSync(join(profile,'package.json'),JSON.stringify({name:'test',dsh:{profile:{bundles:[]}}}));const rootConfig=join(profile,'cordis.yml');writeFileSync(rootConfig,'[]')
 const entry=join(profile,'plugin.mjs'),helper=join(profile,'helper.mjs');writeFileSync(helper,'export const value = 1\n')
 const write=(value:number,failed=false)=>writeFileSync(entry,(mode==='shared'?`import {value} from './helper.mjs'\n`:`const value = ${value}\n`)+`export function apply(ctx, config){ctx.get('reloadTrace').push('start:'+value);${failed?"throw new Error('activation failed')":"if(ctx.get('probeValue')===undefined)ctx.provide('probeValue',value);ctx.effect(()=>()=>ctx.get('reloadTrace').push('stop:'+value))"}}\n`)
 write(1);const patches=[{insert:[{id:'probe',name:'./plugin.mjs'}]}],trace:string[]=[]
 const context:any={dir:profile,home:owner,patchPath:join(profile,'patch.json'),startedBundles:[],installAnchor:join(owner,'package.json'),overlays:patches,telemetryDisabledEnv:undefined}
 let commit:(()=>void)|undefined
 const ctx=await boot('test',rootConfig,patches,(host:any)=>{host.provide('profileContext',context);host.provide('appReady',{onReady(listener:()=>void){commit=listener;return()=>{commit=undefined}}});host.provide('reloadTrace',trace)})
 try{
  await ctx.plugin(Timer);await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0,awaitWriteFinish:false});const hmr:any=ctx.hmr;commit?.()
  const initial=[...ctx.loader.entries()].find((row:any)=>row.options.id==='probe')!,before=initial.fiber;trace.length=0
  if(mode==='unmanaged'){await ctx.plugin(ctx.loader.unwrapExports(await ctx.loader.import(pathToFileURL(entry).href,()=>[])));trace.length=0}
  if(mode==='host')hmr.hostModules=async()=>new Set([pathToFileURL(entry).href])
  if(mode==='comparison-failure')hmr.files.compare=()=>{throw new Error('comparison failed')}
  if(mode!=='unchanged'){
   write(2,mode==='failure');if(mode==='syntax')writeFileSync(entry,'invalid = (\n')
   else if(mode==='shared')writeFileSync(helper,'export const value = 2\n')
   else if(mode==='remove')context.overlays=[]
  }
  let failed=false,outcome:any
  try{outcome=await hmr.runExclusive(()=>hmr.reconcileProfile())}catch{failed=true}
  const current=[...ctx.loader.entries()].find((row:any)=>row.options.id==='probe')
  result.push({mode,failed,value:ctx.get('probeValue')??null,trace:[...trace],same:current!==undefined&&current.fiber===before,
   pending:outcome===undefined?null:outcome.pending.map((item:any)=>({file:basename(new URL(item.url).pathname).replace('.mjs','.py'),reason:item.reason})),restart:outcome?.restartReason??null})
  if(['failure','syntax','remove'].includes(mode)){
   trace.length=0;write(3);context.overlays=patches
   const recovered=await hmr.runExclusive(()=>hmr.reconcileProfile())
   result.push({mode:mode+'-recovered',value:ctx.get('probeValue')??null,trace:[...trace],pending:recovered.pending})
  }
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
