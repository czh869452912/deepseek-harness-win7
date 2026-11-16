import fs from 'node:fs'
import http from 'node:http'
import {getEventListeners} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const t=await load('packages/web/web-deepseek-api/src/transport.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!, 'utf8')), rows:any[]=[], hits:any[]=[]
let entered=false
const server=http.createServer(async(req,res)=>{
 const index=Number(req.url!.split('/')[1]),mode=inputs[index].mode,chunks=[]
 for await(const chunk of req) chunks.push(chunk)
 const headers:any={}
 for(const name of ['x-dsh-auth-token','authorization','x-api-key','content-type','accept','user-agent']) if(req.headers[name]!==undefined)headers[name]=req.headers[name]
 hits.push({path:req.url!.slice(('/'+index).length),headers,body:JSON.parse(Buffer.concat(chunks).toString())})
 const status=mode.startsWith('unauthorized')?401:mode.startsWith('error-')?503:mode==='redirect'?302:200
 let payload:any={value:17}
 if(mode==='error-string')payload={error:'provider-detail'}
 else if(mode==='error-object')payload={error:{message:'provider-detail'}}
 else if(mode==='error-message')payload={message:'provider-detail'}
 else if(mode==='error-null')payload={error:null,message:'fallback-detail'}
 else if(mode.startsWith('unauthorized'))payload={error:{message:'rejected'}}
 else if(mode==='invalid-result')payload=[]
 const encoded=['error-invalid','invalid-json'].includes(mode)?'invalid':JSON.stringify(payload)
 entered=true
 if(mode==='header-abort')return
 res.statusCode=status
 if(status===302)res.setHeader('location','/must-not-follow')
 res.setHeader('content-length',Buffer.byteLength(encoded))
 if(mode.includes('body-abort')){res.write(encoded.slice(0,1));return}
 res.end(encoded)
})
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
const origin=`http://127.0.0.1:${(server.address() as any).port}`
try{
 for(const [index,entry] of inputs.entries()){
  fs.writeFileSync(process.argv[3]!+'.progress.json',JSON.stringify({index,mode:entry.mode}))
  const start=hits.length,events:string[]=[],controller=new AbortController(),mode=entry.mode
  entered=false
  let settle:any,rejectPending:any,dispatching=false
  const pending=new Promise<string>((resolve,reject)=>{settle=resolve;rejectPending=reject})
  const resolve=async(tag:string)=>{
   events.push(tag)
   if(dispatching&&tag==='key-ref'&&mode.startsWith('resolve-'))return pending
   if(tag.endsWith('-error'))throw Error('read-failed')
   return tag.endsWith('-empty')?undefined:tag.startsWith('account')?'account-token':'api-key'
  }
  const configured=async(tag:string)=>{
   events.push('configured:'+tag)
   if(tag.endsWith('configured-error'))throw Error('presence-failed')
   return tag!=='key-ref-unconfigured'
  }
  const rejectToken=async(token:string)=>{events.push('reject:'+token);if(mode==='unauthorized-removal-error')throw Error('remove-failed')}
  const sources=entry.sources.map((tag:string)=>{
   const baseURL=origin+'/'+index+(tag.startsWith('account')?'/account///':'/key/')
   if(tag==='misconfigured')return{kind:tag,message:'route settings invalid'}
   if(tag.startsWith('account'))return{kind:'account',baseURL,resolveToken:()=>resolve(tag),rejectToken}
   return{kind:'api-key',baseURL,key:tag.startsWith('key-ref')?{resolve:()=>resolve(tag),configured:()=>configured(tag)}:tag==='key-empty'?'':'api-key'}
  })
  const auth={sources},available=t.hasDeepSeekWebCredential(auth),ready=await t.isDeepSeekWebAuthReady(auth,'/search')
  dispatching=true
  const request={path:'/search',body:{query:'fixture'},decode:(value:any)=>{if(!value||typeof value!=='object'||!('value'in value))throw t.invalidResponse();return value.value},
   guidance:{subject:'Search',plugin:'web-deepseek-api',custom:index%2===0,baseURLField:'searchBaseURL',apiKeyEnvField:'searchApiKeyEnv'},
   apiKeyHeaders:(key:string)=>({'x-api-key':key}),recordRequest:(endpoint:string)=>{events.push('record:'+endpoint.replace(origin+'/'+index,'<endpoint>'));if(mode==='record-error')throw Error('record-failed')},
   waitToSend:async()=>{events.push('wait');if(mode==='wait-error')throw Error('wait-failed')}}
  if(mode==='pre-abort')controller.abort(Error('private-cancel'))
  const operation=t.dispatchDeepSeekWeb(auth,request,controller.signal)
  // Observe before driving cancellation; the request can reject synchronously.
  const outcome=operation.then((value:any)=>({value}),(error:any)=>{
   let message=error.message.replace(origin+'/'+index,'<endpoint>')
   if(mode==='invalid-json')message=message.replace(/(unprocessable response body: )[\s\S]*?(\n\nThe web request)/,'$1<runtime JSON diagnostic>$2')
   return{code:error.code??null,message}
  })
  if(mode.startsWith('resolve-')){
   while(!events.includes('key-ref'))await new Promise(r=>setTimeout(r,0))
   controller.abort(Error('private-cancel'));await new Promise(r=>setTimeout(r,0))
   if(mode==='resolve-reject-late')rejectPending(Error('late-failed'));else settle('late-key')
  }else if(mode.includes('abort')&&mode!=='pre-abort'){
   while(!entered)await new Promise(r=>setTimeout(r,1))
   await new Promise(r=>setTimeout(r,30));controller.abort(Error('private-cancel'))
  }
  const result=await outcome
  controller.abort(Error('caller-scope-finished'))
  await new Promise(r=>setTimeout(r,0))
  rows.push({index,available,ready,result,events,hits:hits.slice(start),listeners:getEventListeners(controller.signal,'abort').length})
 }
}finally{server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))}
process.stdout.write(JSON.stringify(rows))
