import fs from 'node:fs/promises'
import os from 'node:os'
import {syncBuiltinESMExports} from 'node:module'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Analytics}=await load('packages/client/product-analytics/src/index.ts')
const {updateVolatile,createVolatile}=await load('vendor/cosmokit/src/volatile.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
const originals={platform:os.platform,release:os.release,totalmem:os.totalmem,cpus:os.cpus},arch=Object.getOwnPropertyDescriptor(process,'arch')!,root=process.env.SystemRoot
try{for(const entry of inputs){
 const ctx=new Context(),records:any[]=[],warnings:string[]=[],samples:any[]=[],settings:any[]=[],policy:any[]=[]
 let identityCalls=0,sampleCount=0,stage='schema',error:any=null
 Object.assign(os,{platform:()=>{sampleCount++;return 'win32'},release:()=> '10.0.26300',totalmem:()=>17179869184,cpus:()=>[{model:' Fixture CPU '},{model:'Fixture CPU'}]})
 Object.defineProperty(process,'arch',{...arch,value:'x64'});delete process.env.SystemRoot;syncBuiltinESMExports()
 ctx.logger.warn=(message:string)=>{if(String(message).startsWith('Product analytics'))warnings.push(String(message))}
 ctx.provide('deepseekAccount',{getDeviceIdentity(){identityCalls++
  if(entry.failure==='sync-identity')throw Error('private identity failure')
  return entry.failure==='identity'?Promise.reject(Error('private identity failure')):Promise.resolve(Object.hasOwn(entry,'identity')?structuredClone(entry.identity):{deviceId:'device-'+identityCalls,userId:'user'})
 }})
 ctx.provide('productTelemetry',{emit(record:any){if(entry.failure==='emit')throw Error('private emit failure');records.push(structuredClone(record))}})
 ctx.provide('webServer',{})
 ctx.provide('settings',{configure(options:any){settings.push(options);return ()=>settings.push('disposed')}})
 try{
  const config=Analytics.Config({...entry.config});stage='mount'
  const fiber=await ctx.plugin(Analytics,{...entry.config}),service=ctx.productAnalytics
  stage='done';policy.push(service.enabled())
  const event=(timestamp:number)=>({eventName:'auth_page_view',timestamp,attributes:{os_name:'caller',device_id:'caller-device',app_version:'caller-version'}})
  if(entry.action==='policy'){
   const cancellation=new AbortController(),iterator=service.watchPolicy(cancellation.signal)[Symbol.asyncIterator]()
   policy.push((await iterator.next()).value)
   const next=iterator.next();updateVolatile(fiber.effectiveConfig.enabled,createVolatile(false));fiber.ctx.emit('loader/volatile-update',[['enabled']])
   policy.push((await next).value);cancellation.abort();policy.push((await iterator.next()).done?'done':'unexpected')
   await service.report(event(1))
  }else if(entry.action==='compaction'){
   for(const turn of [null,'turn'])ctx.emit('session/event',{id:'session'},{type:'compaction/start',data:{turn}})
   await new Promise(resolve=>setTimeout(resolve,0));for(const record of records)record.timestamp='<now>'
  }else if(entry.action==='concurrent')await Promise.all([service.report(event(1)),service.report(event(2))])
  else{await service.report(event(1));await service.report(event(2))}
  for(let n=0;n<sampleCount;n++)samples.push({timeoutMillis:config.environmentQueryTimeoutMillis,maxOutputBytes:config.environmentQueryMaxOutputBytes})
  await fiber.dispose();policy.push(service.enabled())
 }catch(failure){if(stage!=='schema')throw failure;error=stage}
 finally{await ctx.fiber.dispose()}
 rows.push({stage,error,records,warnings,identityCalls,samples,settings,policy,after:ctx.get('productAnalytics',false)!==undefined})
}}
finally{Object.assign(os,originals);Object.defineProperty(process,'arch',arch);if(root===undefined)delete process.env.SystemRoot;else process.env.SystemRoot=root;syncBuiltinESMExports()}
console.log(JSON.stringify(rows))
