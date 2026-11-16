import fs from 'node:fs/promises'
import http from 'node:http'
import {load} from './rc022_subagent_fixture.mts'
const {EventLogReporter}=await load('packages/telemetry/otel/src/event-log.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs){
 const captures:any[]=[],warnings:any[]=[]
 let enter!:()=>void,release!:()=>void,second!:()=>void
 const entered=new Promise<void>(resolve=>{enter=resolve}),gate=new Promise<void>(resolve=>{release=resolve}),two=new Promise<void>(resolve=>{second=resolve})
 const server=http.createServer(async(req,res)=>{
  const chunks=[];for await(const chunk of req)chunks.push(chunk)
  const data=Buffer.concat(chunks);captures.push({document:JSON.parse(data.toString('utf8')),bytes:data.length});enter()
  if(captures.length===2)second()
  if(entry.mode==='watchdog'&&captures.length===1)await gate
  res.writeHead(entry.mode==='failure'?400:200,{'content-type':'application/json'});res.end('{}')
 })
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
 const address=server.address() as any,url=`http://127.0.0.1:${address.port}/logs`
 const options={...entry,exporter:{url},processor:{scheduledDelayMillis:2147483647,...entry.processor},
  onFailure(message:string,error?:Error){warnings.push({message,error:error?.message?.replace(url,'<collector>')??null})}}
 let reporter:any,error:any=null
 function emit(record:any){const original=Date.now;Date.now=()=>1700000000999;try{reporter.emit(record)}finally{Date.now=original}}
 try{
  reporter=new EventLogReporter(options)
  if(entry.mode==='late'){await reporter.shutdown();for(const record of entry.records)emit(record)}
  else if(entry.mode==='watchdog'){
   emit(entry.records[0]);await entered
   for(const record of entry.records.slice(1))emit(record)
   await two;release();await reporter.shutdown()
  }else{
   for(const record of entry.records)emit(record)
   if(entry.mode==='timer')await entered
   await reporter.shutdown()
  }
 }catch(failure:any){error=failure.message}
 finally{release();if(reporter!==undefined)await reporter.shutdown();await new Promise<void>(resolve=>server.close(()=>resolve()))}
 rows.push({captures,warnings,error})
}
process.stdout.write(JSON.stringify(rows))
