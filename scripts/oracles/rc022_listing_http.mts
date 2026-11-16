import http from 'node:http'
import zlib from 'node:zlib'
import {load} from './rc022_subagent_fixture.mts'
const {requestModelListing,LISTING_TIMEOUT}=await load('packages/llm/llm-deepseek/src/listing.ts')
const {deadline}=await load('packages/util/timeout/src/index.ts')
const {APP_IDENTITY}=await load('packages/llm/llm/src/attribution.ts')
const cases=['success','override','case-append','gzip','deflate','deflate-raw','broken-gzip','status','invalid-json','invalid-listing','redirect','header-timeout','body-timeout','abort','pre-abort']
const body='{"data":[{"id":"a","api_capabilities":{"anthropic_messages":{}}}]}'
const hits:any[]=[],timers=new Set<ReturnType<typeof setTimeout>>()
const later=(callback:()=>void)=>{const timer=setTimeout(()=>{timers.delete(timer);callback()},150);timers.add(timer)}
const server=http.createServer((req,res)=>{
 hits.push({path:req.url,auth:req.headers['x-api-key']??null,accept:req.headers.accept??null,ua:req.headers['user-agent']??null})
 const send=()=>{
  let payload=Buffer.from(['/invalid-json','/status'].includes(req.url!)?'not-json':req.url==='/invalid-listing'?'{}':body)
  if(['/gzip','/broken-gzip'].includes(req.url!)){
   payload=zlib.gzipSync(payload);res.setHeader('content-encoding','gzip')
   if(req.url==='/broken-gzip')payload=payload.subarray(0,payload.length-5)
  }
  if(['/deflate','/deflate-raw'].includes(req.url!)){
   payload=req.url==='/deflate'?zlib.deflateSync(payload):zlib.deflateRawSync(payload);res.setHeader('content-encoding','deflate')
  }
  res.statusCode=req.url==='/status'?401:req.url==='/redirect'?302:200
  if(req.url==='/redirect')res.setHeader('location','/leaked')
  res.setHeader('content-length',Buffer.byteLength(payload))
  if(req.url==='/body-timeout'){res.write(payload.slice(0,1));later(()=>res.end(payload.slice(1)))}
  else res.end(payload)
 }
 if(['/header-timeout','/abort'].includes(req.url!))later(send);else send()
})
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
const origin='http://127.0.0.1:'+(server.address() as any).port,rows:any[]=[]
try{
 for(const name of cases){
  const parent=new AbortController(),limit=deadline(parent.signal,name.includes('timeout')?80:2000,LISTING_TIMEOUT)
  if(name==='pre-abort')parent.abort(new Error('caller'))
  const timer=name==='abort'?setTimeout(()=>parent.abort(),40):undefined
  const headers:Record<string,string>={'x-api-key':'test-secret'}
  if(name==='override')Object.assign(headers,{accept:'custom/type','user-agent':'custom/1'})
  if(name==='case-append')Object.assign(headers,{Accept:'custom/type','User-Agent':'custom/1'})
  const before=hits.length
  let result:any
  try{result={value:await requestModelListing(origin+'/'+name,headers,limit.signal)}}
  catch(error:any){result={error:error.message.replaceAll(origin,'<origin>'),code:error.code??null,status:error.failure?.status??null}}
  finally{limit[Symbol.dispose]();clearTimeout(timer)}
  const requests=hits.slice(before)
  for(const hit of requests){if(hit.ua!=='custom/1'){
   const extra=name==='case-append'?', custom/1':''
   if(hit.ua!==`${APP_IDENTITY.product}/${APP_IDENTITY.version} (+${APP_IDENTITY.url})`+extra)throw new Error('Attribution identity mismatch')
   hit.ua='<active-runtime-attribution>'+extra
  }}
  rows.push({name,requests,...result})
 }
 console.log(JSON.stringify(rows))
}finally{
 for(const timer of timers)clearTimeout(timer)
 server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))
}
