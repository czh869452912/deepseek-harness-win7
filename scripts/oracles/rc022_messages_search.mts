import fs from 'node:fs'
import http from 'node:http'
import {getEventListeners} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const p=await load('packages/web/web-search-deepseek/src/provider.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),hits:any[]=[],rows:any[]=[]
const defaults={apiKeyEnv:'DEEPSEEK_API_KEY',model:'deepseek-v4-flash',apiVersion:'2023-06-01',maxTokens:4096,maxUses:5}
const answer={content:[{type:'text',citations:[{url:'https://page.test',cited_text:'first citation'}]},
 {type:'web_search_tool_result',content:[{type:'web_search_result',url:'https://page.test',title:'Page',page_age:'today'},
 {type:'web_search_result',url:'https://page.test',title:'duplicate'}]}]}
let entered=false
const server=http.createServer(async(req,res)=>{
 const index=Number(req.url!.split('/')[1]),mode=inputs[index].mode,chunks=[],headers:any={}
 for await(const chunk of req)chunks.push(chunk)
 for(const key of ['x-dsh-auth-token','x-api-key','authorization','anthropic-version','content-type','accept','user-agent'])if(req.headers[key]!==undefined)headers[key]=req.headers[key]
 hits.push({path:req.url,headers,body:JSON.parse(Buffer.concat(chunks).toString())});entered=true
 if(mode==='header-abort')return
 res.statusCode=mode.startsWith('unauthorized')?401:mode.startsWith('error-')?503:mode==='redirect'?302:200
 let payload:any=answer
 if(mode==='no-results')payload={content:[]}
 else if(mode==='error-string')payload={error:'detail'}
 else if(mode==='error-object')payload={error:{message:'detail'}}
 else if(mode==='error-fallback')payload={error:{message:null},message:'fallback-detail'}
 else if(mode.startsWith('unauthorized'))payload={error:{message:'rejected'}}
 const data=['invalid-json','error-invalid'].includes(mode)?'invalid':JSON.stringify(payload)
 res.setHeader('content-type','application/json');res.setHeader('content-length',Buffer.byteLength(data))
 if(res.statusCode===302)res.setHeader('location','/must-not-follow')
 if(mode.includes('body-abort')||mode==='dropped-body'){res.write(data.slice(0,1));if(mode==='dropped-body')setTimeout(()=>res.destroy(),5);return}
 res.end(data)
})
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
const origin=`http://127.0.0.1:${(server.address() as any).port}`
try{
 rows.push({description:new p.DeepSeekSearchProvider(()=>defaults).description})
 for(const [index,entry]of inputs.entries()){
  const mode=entry.mode,events:string[]=[],records:any[]=[],controller=new AbortController(),start=hits.length;entered=false
  let settle:any,rejectPending:any,reads=0
  const pending=new Promise<string>((resolve,reject)=>{settle=resolve;rejectPending=reject})
  const resolve=async(tag:string,endpoint?:string)=>{
   events.push(endpoint?'account:'+endpoint.replace(origin,'<origin>'):'key')
   if(tag==='held')return pending
   if(tag.endsWith('error')){if(tag.endsWith('type-error'))throw TypeError('read-failed');throw Error('read-failed')}
   return tag.endsWith('empty')?undefined:endpoint?'account-token':'api-key'
  }
  const reject=async(token:string)=>{events.push('reject:'+token);if(mode==='unauthorized-removal-error')throw Error('remove-failed');if(mode==='unauthorized-reject-abort')controller.abort(Error('rejected grant'))}
  let current:any={...defaults,baseURL:`${origin}/${index}`,recordRequest:(request:any)=>{records.push(request);if(mode==='record-error')throw Error('record-failed')}}
  if(entry.account!==null){current.resolveAccountToken=(endpoint:string)=>resolve(entry.account,endpoint);current.rejectAccountToken=reject}
  if(['literal','empty'].includes(entry.key))current.apiKey=entry.key==='literal'?'literal-key':''
  else if(entry.key!==null)current.resolveApiKey=()=>resolve(entry.key)
  const provider=new p.DeepSeekSearchProvider(()=>{reads++;return current}),available=provider.available()
  if(mode==='pre-abort')controller.abort(Error('caller cancelled'))
  const request={query:'fixture'},operation=provider.search(request,controller.signal)
  const outcome=operation.then((value:any)=>({value}),(error:any)=>{
   let message=error.message.replaceAll(origin,'<origin>')
   if(mode==='invalid-json')message=message.replace(/(unprocessable response body: )[\s\S]*?(\n\nThe web request)/,'$1<runtime JSON diagnostic>$2')
   return{code:error.code??null,message}
  })
  if(mode.startsWith('resolve-')||mode==='snapshot'&&entry.account==='held'){
   while(!events.length)await new Promise(r=>setTimeout(r,0))
   if(mode.startsWith('resolve-')){controller.abort(Error('caller cancelled'));await new Promise(r=>setTimeout(r,0));if(mode==='resolve-reject-late')rejectPending(Error('late-failed'));else settle('late-token')}
   else{current={...defaults,baseURL:'https://must-not-use.invalid',apiKey:'changed-key'};request.query='changed-query';settle('captured-token')}
  }else if(mode==='snapshot')request.query='changed-query'
  else if(['header-abort','body-abort','unauthorized-body-abort'].includes(mode)){
   while(!entered)await new Promise(r=>setTimeout(r,1));await new Promise(r=>setTimeout(r,30));controller.abort(Error('caller cancelled'))
  }
  const result=await outcome;controller.abort(Error('scope disposed'));await new Promise(r=>setTimeout(r,0))
  rows.push({available,reads,result,events,records,hits:hits.slice(start),listeners:getEventListeners(controller.signal,'abort').length})
 }
}finally{server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))}
process.stdout.write(JSON.stringify(rows).replaceAll(origin,'<origin>'))
