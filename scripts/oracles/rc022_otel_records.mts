import fs from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
const {SessionLogReporter,resolveSessionLogLimits}=await load('packages/telemetry/otel/src/session-log.ts')
const {EventLogReporter}=await load('packages/telemetry/otel/src/event-log.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs){
 try{
  if(entry.kind==='limits'){
   // Construct the real pipeline when limit validation succeeds; no records
   // are emitted, so neither constructor nor shutdown performs a request.
   const value=resolveSessionLogLimits(entry.options)
   const reporter=new SessionLogReporter({...entry.options,exporter:{url:'http://127.0.0.1:9/logs'},scope:{name:'fixture'},resourceAttributes:{},onFailure(){}})
   await reporter.shutdown();rows.push({value});continue
  }
  const options={exporter:{url:'http://127.0.0.1:9/logs'},scope:{name:'fixture'},resourceAttributes:{},onFailure(){}}
  const reporter:any=entry.kind==='session'?new SessionLogReporter(options):new EventLogReporter(options)
  let value:any
  reporter.logger.emit=(record:any)=>{value=record}
  const original=Date.now;Date.now=()=>1700000000999
  try{if(entry.kind==='session')reporter.reportSessionLog(entry.record);else reporter.emit(entry.record)}finally{Date.now=original}
  await reporter.shutdown();rows.push({value})
 }catch(error:any){rows.push({error:error.message})}
}
process.stdout.write(JSON.stringify(rows))
