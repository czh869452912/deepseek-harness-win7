import fs from 'node:fs/promises'
import path from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
process.env.DSH_HOME=path.dirname(process.argv[4]!)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Backend}=await load('packages/session/session-telemetry-otel/src/index.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs){
 const ctx=new Context(),options:any[]=[],records:any[]=[],warnings:string[]=[];let error:any=null
 ctx.logger.warn=(message:string)=>warnings.push(String(message))
 ctx.provide('otel',{createSessionLogReporter(selected:any){
  const {onFailure,...plain}=selected;options.push(structuredClone(plain))
  return {reportSessionLog(value:any){records.push(structuredClone(value))},async shutdown(){},stopPending(){}}
 }})
 ctx.provide('sessions',{list:()=>[]})
 ctx.on('session-telemetry/record',(record:any,next:any)=>{
  if(entry.action==='redact')record.body={redacted:true}
  if(entry.action==='remove-source')delete record.sourceEvent
  return next()
 })
 const config={exporter:{url:'http://fixture.test/logs'},...entry.config}
 try{
  const backend=new Backend(ctx,config)
  const events=[{seq:0,time:1700000000000,type:'fixture/synthetic',data:{text:'private'}},
   {seq:1,time:1700000000001,type:'feedback/record',data:{text:'consent'}}]
  const session={id:'fixture',events,inheritedEventCount:entry.action==='seeded'?2:0,firstLiveSeq:0,
   header:{version:4,cwd:'/workspace',isSeeded:false},snapshotEvents:(offset=0)=>events.slice(offset),eventAt:(seq:number)=>events[seq]}
  backend.emit({channel:'ledger',time:1,severity:'info',attributes:{},body:{direct:'withheld'}})
  if(entry.action!=='none'){
   const event=entry.action==='noncanonical'?structuredClone(events[1]):events[1]
   ctx.emit('session/event',session,event);ctx.emit('session/event',session,event)
  }
  await backend.shutdown()
 }catch(failure:any){error=failure.message}
 finally{await ctx.fiber.dispose()}
 rows.push({options,records,warnings,error})
}
process.stdout.write(JSON.stringify(rows))
