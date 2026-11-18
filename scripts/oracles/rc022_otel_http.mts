import fs from 'node:fs/promises'
import http from 'node:http'
import https from 'node:https'
import path from 'node:path'
import {gunzipSync,gzipSync,deflateSync,brotliCompressSync,zstdCompressSync} from 'node:zlib'
import {load} from './rc022_subagent_fixture.mts'
const {SessionLogReporter}=await load('packages/telemetry/otel/src/session-log.ts')
const {logTransportOptions}=await load('packages/telemetry/otel/src/transport.ts')
const {createEventLogExporter}=await load('packages/telemetry/otel/src/event-transport.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
const record={sessionId:'fixture-session',event:{seq:1,time:1700000000123.5,type:'fixture',data:{text:'synthetic'}},attributes:{flag:true,count:2,fraction:1.25}}
const environmentNames=['OTEL_EXPORTER_OTLP_TIMEOUT','OTEL_EXPORTER_OTLP_LOGS_TIMEOUT','OTEL_EXPORTER_OTLP_COMPRESSION','OTEL_EXPORTER_OTLP_LOGS_COMPRESSION']
const cert=await fs.readFile(path.join(path.dirname(process.argv[3]!),'localhost-cert.pem'))
const key=await fs.readFile(path.join(path.dirname(process.argv[3]!),'localhost-key.pem'))
for(const entry of inputs){
 if(entry.mode==='config'){
  const names=[...new Set([...environmentNames,...Object.keys(entry.env)])],previous=Object.fromEntries(names.map(name=>[name,process.env[name]]))
  for(const name of names)delete process.env[name]
  Object.assign(process.env,entry.env)
  try{
   const config=logTransportOptions({url:'http://fixture.test/logs',...entry.options})
   rows.push({value:{timeoutMillis:config.timeoutMillis,compression:config.compression,concurrencyLimit:config.concurrencyLimit,headers:await config.headers()}})
  }catch(error:any){rows.push({error:error.message})}
  finally{for(const name of names){if(previous[name]===undefined)delete process.env[name];else process.env[name]=previous[name]}}
  continue
 }
 const hits:any[]=[],warnings:any[]=[],agentCalls:string[]=[];let calls=0,agentDestroyed=0
 let controller:AbortController|undefined,timer:any
 const handle=async(req:any,res:any)=>{
  const chunks=[];for await(const chunk of req)chunks.push(chunk)
  let data=Buffer.concat(chunks);if(req.headers['content-encoding']==='gzip')data=gunzipSync(data)
  hits.push({document:JSON.parse(data.toString('utf8')),headers:{contentType:req.headers['content-type']??null,
   authorization:req.headers.authorization??null,tenant:req.headers['x-tenant']??null,agent:req.headers['user-agent']??null,compression:req.headers['content-encoding']??null}})
  if(entry.event)hits[hits.length-1].headers.acceptEncoding=req.headers['accept-encoding']??null
  const mode=entry.mode,attempt=hits.length
  if(entry.abort==='delay'&&attempt===1)timer=setTimeout(()=>controller!.abort(),30)
  if(mode==='reset-once'&&attempt===1){req.socket.destroy();return}
  const status=mode==='created'?201:mode==='redirect'?302:mode==='bad-request'?400:mode==='server-error'?500:
   ['retry-exhausted','retry-deadline'].includes(mode)||mode==='retry-once'&&attempt===1?503:200
  let body=mode==='bad-json'?Buffer.from('bad-json'):mode==='oversized'?Buffer.alloc(4194305,120):Buffer.from('{}')
  const compress:any={gzip:gzipSync,deflate:deflateSync,br:brotliCompressSync,zstd:zstdCompressSync}
  if(entry.responseEncoding)body=compress[entry.responseEncoding](body)
  if(mode==='timeout')await new Promise(resolve=>setTimeout(resolve,200))
  res.writeHead(status,{'content-length':mode==='truncated'?10:body.length,'content-type':'application/json',
   ...(entry.responseEncoding?{'content-encoding':entry.responseEncoding}:{}),
   ...(status===302?{location:'/redirected'}:{}),...(status===503?{'retry-after':entry.retryAfter??(mode==='retry-deadline'?'20':'0')}:{})})
  res.end(body);if(mode==='truncated')res.socket?.end()
 }
 const server=entry.tls?https.createServer({cert,key},handle):http.createServer(handle)
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
 const address=server.address() as any,options={url:`${entry.tls?'https://localhost':'http://127.0.0.1'}:${address.port}/logs`,...entry.options}
 if(['ca','identity'].includes(entry.agent))options.httpAgentOptions={ca:cert,...(entry.agent==='identity'?{cert,key}:{})}
 if(entry.agent==='insecure')options.httpAgentOptions={rejectUnauthorized:false}
 if(['factory','factory-error'].includes(entry.agent))options.httpAgentOptions=(protocol:string)=>{
  agentCalls.push(protocol)
  if(entry.agent==='factory-error')throw Object.assign(new Error('synthetic callback failure'),{code:'ECONNRESET'})
  const agent=protocol==='https:'?new https.Agent({ca:cert}):new http.Agent()
  const destroy=agent.destroy.bind(agent);agent.destroy=()=>{agentDestroyed++;destroy()}
  return agent
 }
 if(entry.agent==='headers-error')options.headers=()=>{throw Object.assign(new Error('synthetic callback failure'),{code:'ECONNRESET'})}
 if(['timeout','retry-deadline'].includes(entry.mode))options.timeoutMillis=50
 if(entry.abort==='delay')options.timeoutMillis=1000
 if(entry.dynamic)options.headers=async()=>({Authorization:'Bearer synthetic-'+(++calls)})
 const names=[...new Set([...environmentNames,...Object.keys(entry.env)])],previous=Object.fromEntries(names.map(name=>[name,process.env[name]]))
 for(const name of names)delete process.env[name]
 Object.assign(process.env,entry.env)
 let reporter:any
 try{
  reporter=new SessionLogReporter({exporter:options,scope:{name:'fixture',version:'1'},resourceAttributes:{},
   onFailure(message:string,error?:Error){warnings.push({message,error:error?.message??null})}})
  if(entry.event){
   await reporter.processor.exporter.shutdown()
   controller=new AbortController()
   if(entry.abort==='before')controller.abort()
   reporter.processor.exporter=createEventLogExporter(options,controller.signal)
  }
  reporter.reportSessionLog(record);await reporter.shutdown()
 }finally{
  if(reporter!==undefined)await reporter.shutdown()
  if(timer!==undefined)clearTimeout(timer)
  for(const name of names){if(previous[name]===undefined)delete process.env[name];else process.env[name]=previous[name]}
  await new Promise<void>(resolve=>server.close(()=>resolve()))
 }
 if(entry.event)for(const warning of warnings)if(warning.error)warning.error=warning.error.replace(options.url,'<collector>')
 rows.push({hits,warnings,headerCalls:calls,agentCalls,agentDestroyed})
}
process.stdout.write(JSON.stringify(rows))
