import fs from 'node:fs/promises'
import http from 'node:http'
import {gunzipSync} from 'node:zlib'
import {load} from './rc022_subagent_fixture.mts'
const {SessionLogReporter}=await load('packages/telemetry/otel/src/session-log.ts')
const {EventLogReporter}=await load('packages/telemetry/otel/src/event-log.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs){
 const captures:any[]=[],warnings:any[]=[]
 const server=http.createServer(async(req,res)=>{
  const chunks=[];for await(const chunk of req)chunks.push(chunk)
  const compressed=Buffer.concat(chunks),data=req.headers['content-encoding']==='gzip'?gunzipSync(compressed):compressed
  captures.push({document:JSON.parse(data.toString('utf8')),bytes:data.length})
  res.writeHead(200,{'content-type':'application/json'});res.end('{}')
 })
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
 const address=server.address() as any
 const options={exporter:{url:`http://127.0.0.1:${address.port}/logs`,headers:entry.headers??{},compression:entry.compression??'none'},
  scope:entry.scope,resourceAttributes:entry.resourceAttributes,
  processor:{maxExportBatchSize:512,maxQueueSize:2048,scheduledDelayMillis:2147483647,...entry.processor},
  ...(entry.maxRequestBytes===undefined?{}:{maxRequestBytes:entry.maxRequestBytes}),
  onFailure(message:string,error?:Error){warnings.push({message,error:error?.message??null})}}
 let reporter:any,error:any=null
 try{
  reporter=entry.kind==='session'?new SessionLogReporter(options):new EventLogReporter(options)
  const original=Date.now;Date.now=()=>1700000000999
  try{for(const record of entry.records){if(entry.kind==='session')reporter.reportSessionLog(record);else reporter.emit(record)}}finally{Date.now=original}
  await reporter.shutdown()
 }catch(failure:any){error=failure.message}
 finally{if(reporter!==undefined)await reporter.shutdown();await new Promise<void>(resolve=>server.close(()=>resolve()))}
 rows.push({captures,warnings,error})
}
process.stdout.write(JSON.stringify(rows))
