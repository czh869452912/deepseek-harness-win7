import fs from 'node:fs'
import http from 'node:http'
import zlib from 'node:zlib'
import path from 'node:path'
import crypto from 'node:crypto'
import {load} from './rc022_subagent_fixture.mts'
const {DeepSeekAdapter}=await load('packages/llm/llm-deepseek/src/adapter.ts')
const {LlmError}=await load('packages/llm/llm/src/index.ts')
const {DeepSeekFileStore}=await load('packages/llm/llm-deepseek/src/file-store.ts')
const {DeepSeekUploadIndex}=await load('packages/llm/llm-deepseek/src/upload-index.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),hits:any[]=[],rows:any[]=[],attempts=new Map(),uploads=new Map(),timers=new Set<ReturnType<typeof setTimeout>>()
const delay=(callback:()=>void)=>{const timer=setTimeout(()=>{timers.delete(timer);callback()},300);timers.add(timer)}
const server=http.createServer(async(req,res)=>{
 const index=Number(req.url!.split('/')[1]),mode=input.modes[index]
 const chunks=[];for await(const chunk of req)chunks.push(chunk)
 if(req.url!.endsWith('/files')){
  const count=(uploads.get(index)??0)+1;uploads.set(index,count)
  const boundary=req.headers['content-type']!.split('boundary=')[1]!
  const fields=Buffer.concat(chunks).toString('latin1').split('--'+boundary).slice(1,-1).map(part=>{const split=part.indexOf('\r\n\r\n');return{header:Buffer.from(part.slice(2,split),'latin1').toString('utf8'),data:Buffer.from(part.slice(split+4,-2),'latin1').toString('base64')}})
  hits.push({path:req.url!.slice(('/'+index).length),fields})
  res.end(JSON.stringify({id:'file-'+count,type:'file',mime_type:'image/png',size_bytes:3,created_at:'2026-11-17T00:00:01Z',filename:'uploaded.png'}));return
 }
 const count=(attempts.get(index)??0)+1;attempts.set(index,count)
 const headers:any={};for(const key of ['x-api-key','anthropic-version','anthropic-beta','x-deepseek-harness-user-id','x-deepseek-harness-session-id','x-deepseek-harness-compact'])headers[key]=req.headers[key]??null
 hits.push({path:req.url!.slice(('/'+index).length),body:JSON.parse(Buffer.concat(chunks).toString('utf8')),headers})
 let status=200,payload=Buffer.from(input.events.map((event:any)=>'event: '+event.type+'\ndata: '+JSON.stringify(event)+'\n\n').join(''))
 if(mode==='malformed')payload=Buffer.from('event: message_start\ndata: {\n\n')
 if(mode==='inband-error')payload=Buffer.from('event: error\ndata: {"type":"error","error":{"type":"rate_limit_error","message":"busy"}}\n\n')
 if(mode==='empty'){status=204;payload=Buffer.alloc(0)}
 if(mode==='empty205'){status=205;payload=Buffer.alloc(0)}
 if(mode==='truncated-length')payload=Buffer.from('event: message_start\ndata: {')
 if(mode==='redirect')status=302
 if(['auth','mapped','mapper-fail'].includes(mode)){status=401;payload=Buffer.from('{"error":{"message":"bad key"}}')}
 if(mode==='quota'){status=402;payload=Buffer.from('{"error":{"message":"storage quota exceeded"}}')}
 if(['retry-after','duplicate-headers'].includes(mode)){status=503;payload=Buffer.from('{"error":{"message":"busy"}}')}
 if(mode==='gateway'){status=502;payload=Buffer.from('gateway failed')}
 if(mode==='stale-file'&&count===1){status=400;payload=Buffer.from('{"error":{"message":"file-a not found"}}')}
 if(mode==='real-stale'&&count===1){status=400;payload=Buffer.from('{"error":{"message":"file-1 not found"}}')}
 if(mode==='gzip')payload=zlib.gzipSync(payload)
 if(mode==='concat-gzip')payload=Buffer.concat([zlib.gzipSync(payload.subarray(0,20)),zlib.gzipSync(payload.subarray(20))])
 const send=()=>{
  res.statusCode=status
  if(mode==='redirect')res.setHeader('location','/leaked')
  if(['gzip','concat-gzip'].includes(mode))res.setHeader('content-encoding','gzip')
  if(mode==='retry-after'){res.setHeader('retry-after','2');res.setHeader('request-id','r1')}
  if(mode==='duplicate-headers'){res.setHeader('retry-after',['1','2']);res.setHeader('request-id',['a','b'])}
  if(mode==='broken-chunk'){res.setHeader('transfer-encoding','chunked');res.write('event: message_start\ndata: {',()=>res.socket?.end());return}
  res.setHeader('content-length',payload.length+(mode==='truncated-length'?10:0))
  if(mode==='truncated-length'){res.write(payload,()=>res.socket?.end());return}
  if(['idle-body','cancel-body'].includes(mode)){res.write(payload.subarray(0,1));delay(()=>res.end(payload.subarray(1)))}else res.end(payload)
 }
 if(['idle-header','cancel-header'].includes(mode))delay(send);else send()
})
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
try{
 for(const [index,mode] of input.modes.entries()){
  const options={...input.config,baseURL:`http://127.0.0.1:${(server.address() as any).port}/${index}/anthropic`,streamIdleTimeoutMs:mode.startsWith('idle-')||mode==='slow-consumer'?80:2000}
  const calls:any[]=[],chunks:any[]=[],start=hits.length
  const ref={attachmentId:'sha256:'+'a'.repeat(64),mediaType:'image/png',bytes:3,width:2,height:2,hasAlpha:false}
  const version={attachment:ref,variantId:'sha256:'+'b'.repeat(64),mediaType:'image/png',bytes:3,width:2,height:2,hasAlpha:false,data:new Uint8Array([97,98,99])}
  const files={async ensureUploaded(){calls.push('files');if(mode==='inline-fallback')throw new Error('upload unavailable');return{record:{fileId:'file-a'}}},async invalidate(generations:any){calls.push({invalidate:generations})}}
  const prepareExtensions=async(request:any)=>{
   calls.push({extensions:{sessionId:request.sessionId??null,purpose:request.purpose??null}})
   if(mode==='extension-prepare-fail')throw new Error('prepare unavailable')
   return{fields:{custom:{enabled:true}},async accept(){calls.push('accept');if(mode==='extension-accept-fail')throw new Error('accept unavailable')}}
  }
  const resolveAuth=async()=>{
   calls.push('auth')
   return{headers:{'x-api-key':'secret'},...['mapped','mapper-fail'].includes(mode)?{async onRequestError(){calls.push('mapper');if(mode==='mapper-fail')throw new Error('mapper unavailable');return new LlmError('credential refreshed','AUTH')}}:{}}
  }
  const indexPath=mode.startsWith('real-')?path.join(path.dirname(process.argv[3]!),'files','source-'+index,'index.json'):undefined
  const real=indexPath?new DeepSeekFileStore({index:new DeepSeekUploadIndex(indexPath),now:()=>10000}):undefined
  const adapter=new DeepSeekAdapter({options:()=>options,resolveAuth,resolveUserId:()=> 'user-id',resolveFiles:()=>real??files,resolveAttachments:()=>({async readImageRequest(){return version}}),prepareExtensions,onExtensionsUnaccepted(){calls.push('unaccepted')}})
  const content:any[]=[{type:'text',text:'hi'}];if(['image','stale-file','inline-fallback','image-tool-changes'].includes(mode)||mode.startsWith('real-'))content.push({type:'image',attachment:ref})
  if(mode==='real-upload')content.push({type:'image',attachment:ref})
  const controller=new AbortController(),request:any={provider:'deepseek-official',model:'m',messages:[{role:'user',content,source:{kind:'user'}}],sessionId:'session',purpose:mode==='compaction'?'compaction':'response',...mode.startsWith('cancel-')?{signal:controller.signal}:{}}
  if(['tool-changes','image-tool-changes'].includes(mode)){request.messages.push({role:'developer',source:{kind:'tool-runtime'},content:[{type:'tool-addition',toolName:'read'}]});request.tools=[{name:'read',description:'Read a file',parameters:{type:'object'},deferLoading:true}]}
  const abortTimer=mode.startsWith('cancel-')?setTimeout(()=>controller.abort(new Error('caller stopped')),80):undefined
  let result:any
  try{for await(const chunk of adapter.stream(request)){chunks.push(chunk);if(mode==='early-close')break;if(mode==='slow-consumer'&&chunks.length===1)await new Promise(resolve=>setTimeout(resolve,160))}result={chunks}}
  catch(error:any){result={chunks,error:error.failure??{message:error.message}}}
  finally{clearTimeout(abortTimer)}
  const row:any={mode,result,calls,hits:hits.slice(start)}
  if(indexPath){
   const disk=JSON.parse(fs.readFileSync(indexPath,'utf8'))
   const scope=crypto.createHash('sha256').update(options.baseURL+'/v1\0'+JSON.stringify([['x-api-key','secret']])).digest('hex')
   for(const record of disk.records){if(record.scope!==scope)throw new Error('unexpected namespace');record.scope='<verified-origin-scope>'}
   row.disk=disk
  }
  rows.push(row)
 }
}finally{for(const timer of timers)clearTimeout(timer);server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))}
process.stdout.write(JSON.stringify(rows))
