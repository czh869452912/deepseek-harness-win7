import fs from 'node:fs/promises'
import http from 'node:http'
import {load} from './rc022_subagent_fixture.mts'
const {SessionLogReporter}=await load('packages/telemetry/otel/src/session-log.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs){
 const captures:any[]=[],warnings:any[]=[]
 let enter!:()=>void,release!:()=>void,warned!:()=>void
 const entered=new Promise<void>(resolve=>{enter=resolve}),gate=new Promise<void>(resolve=>{release=resolve}),warning=new Promise<void>(resolve=>{warned=resolve})
 const server=http.createServer(async(req,res)=>{
  const chunks=[];for await(const chunk of req)chunks.push(chunk)
  const data=Buffer.concat(chunks);captures.push({document:JSON.parse(data.toString('utf8')),bytes:data.length});enter()
  if(['watchdog','stop'].includes(entry.mode)&&captures.length===1)await gate
  res.writeHead(200,{'content-type':'application/json'});res.end('{}')
 })
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
 const address=server.address() as any
 const options={...entry,exporter:{url:`http://127.0.0.1:${address.port}/logs`},
  processor:{scheduledDelayMillis:2147483647,...entry.processor},
  onFailure(message:string,error?:Error){warnings.push({message,error:error?.message??null});if(message.includes('exceeded exportTimeoutMillis'))warned()}}
 let reporter:any,error:any=null
 try{
  reporter=new SessionLogReporter(options)
  if(entry.mode==='late'){await reporter.shutdown();for(const record of entry.records)reporter.reportSessionLog(record)}
  else if(['watchdog','stop'].includes(entry.mode)){
   reporter.reportSessionLog(entry.records[0]);await entered
   if(entry.mode==='watchdog')await warning
   for(const record of entry.records.slice(1))reporter.reportSessionLog(record)
   if(entry.mode==='stop')reporter.stopPending()
   release();await reporter.shutdown()
  }else{
   for(const record of entry.records)reporter.reportSessionLog(record)
   if(entry.mode==='timer')await entered
   await reporter.shutdown()
  }
 }catch(failure:any){error=failure.message}
 finally{release();if(reporter!==undefined)await reporter.shutdown();await new Promise<void>(resolve=>server.close(()=>resolve()))}
 rows.push({captures,warnings,error})
}
process.stdout.write(JSON.stringify(rows))
