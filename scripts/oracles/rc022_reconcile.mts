import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {boot,reconcileProfilePatches}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/index.ts')).href)
const result:any[]=[],raw:any[]=[]
for(const mode of JSON.parse(readFileSync(input,'utf8'))){
 const directory=resolve(dirname(input),'files/source',mode);mkdirSync(directory,{recursive:true});const path=join(directory,'root.json');writeFileSync(path,'[]')
 const row:any={id:'candidate',name:'cordis:broken',config:{revision:1}}
 if(['pending','required-pending'].includes(mode))row.name='cordis:waiting'
 if(['held','dispose-error'].includes(mode))row.name='cordis:held'
 if(mode.startsWith('missing'))row.name='cordis:absent'
 const patches=mode==='new'?[]:[{insert:[row]}],entered=Promise.withResolvers<void>(),release=Promise.withResolvers<void>(),events:any[]=[]
 let warning='';const write=process.stderr.write;process.stderr.write=((chunk:any)=>{warning+=String(chunk);return true}) as any
 let ctx:any
 try{ctx=await boot('probe',path,patches,host=>{
  host.loader.builtins.broken=()=>{throw new Error('candidate activation failed')}
  host.loader.builtins.waiting={inject:['missingService'],apply(){}}
  host.loader.builtins.held=(owner:any)=>{owner.effect(()=>async()=>{entered.resolve();if(mode==='held')await release.promise;else throw new Error('dispose failed')})}
  host.on('app-boot/config-reload',(...args:any[])=>{events.push(args)})
 })}finally{process.stderr.write=write}
 try{
  const before=[...ctx.loader.entries()].find((row:any)=>row.options.id==='candidate'),fiber=before?.fiber
  const next:any[]=['remove','held','dispose-error'].includes(mode)?[]:[{insert:[row]}]
  if(['changed','missing-changed'].includes(mode))next.push({id:'candidate',config:{revision:2}})
  let done=false,error:any=null,warnings:string[]=[],settled_before:any=null
  process.stderr.write=((chunk:any)=>{warning+=String(chunk);return true}) as any
  try{
   const operation=reconcileProfilePatches(ctx,next,'probe',['required','required-pending'].includes(mode)?['candidate']:[]).finally(()=>{done=true})
   if(mode==='held'){await entered.promise;settled_before=done;release.resolve()}
   try{warnings=await operation}catch(e){error=(e as Error).message}
  }finally{process.stderr.write=write}
  const after=[...ctx.loader.entries()].find((row:any)=>row.options.id==='candidate')
  result.push({mode,fatal:error!==null,warnings:warnings.length,same_entry:before===after,same_fiber:!!after&&fiber===after.fiber,removed:!after,events,settled_before,active:!!after&&after.fiber?.state===2,error_mentions_candidate:error!==null&&error.includes('candidate'),warning_kind:warnings.length?(warnings[0]!.includes('pending')?'pending':'failed'):null})
  raw.push({mode,error,warnings,log:warning})
 }finally{release.resolve();await ctx.fiber.dispose()}
}
writeFileSync(resolve(dirname(input),'source-diagnostics.json'),JSON.stringify(raw))
process.stdout.write(JSON.stringify(result))
