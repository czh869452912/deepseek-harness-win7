import fs from 'node:fs'
import path from 'node:path'
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const entry=require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')
const temporary=path.join(path.dirname(entry),'.rc022-probe-'+process.pid+'.mjs');let created=false
function normalize(value:any):any{
 if(value instanceof Error)return {name:value.name,message:value.message,...'code'in value?{code:value.code}:{},...'data'in value&&value.data!==undefined?{data:normalize(value.data)}:{}}
 if(Array.isArray(value))return value.map(normalize)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([,v])=>v!==undefined).map(([k,v])=>[k,normalize(v)]))
 return value
}
try{
 fs.writeFileSync(temporary,fs.readFileSync(entry,'utf8')+'\nexport {negotiateEra as rc022Negotiate,disarmSpentCloseGuard as rc022Disarm};\n',{flag:'wx'});created=true
 const {rc022Negotiate,rc022Disarm}=await import(pathToFileURL(temporary).href)
 const rows=[]
 for(const spec of input){
  const events:any[]=[],requests:any[]=[];let starts=0,index=0
  const savedMessage=()=>events.push('message'),savedError=(error:Error)=>events.push(['error',error.message]),savedClose=()=>events.push('close')
  const transport:any={onmessage:savedMessage,onerror:savedError,onclose:savedClose,
   async start(){starts++;if(spec.startError)throw new Error('start failed')},
   async send(packet:any){
    requests.push(packet);const step=spec.steps[index++]??{kind:'timeout'}
    transport.onmessage?.({jsonrpc:'2.0',method:'notifications/fixture',params:{}})
    transport.onmessage?.({jsonrpc:'2.0',id:'unrelated',result:{}})
    for(const junk of [{result:null},{result:{} ,extra:true},{error:{code:'bad',message:'bad'}},{result:{},error:{code:-32601,message:'bad'}}])transport.onmessage?.({jsonrpc:'2.0',id:packet.id,...junk})
    if(step.kind==='closed'){transport.onclose?.();return}
    if(step.kind==='timeout')return
    if(step.kind==='error'){const error=new Error('send failed');transport.onerror?.(error);throw error}
    transport.onmessage?.({jsonrpc:'2.0',id:packet.id,...step.kind==='rpc'?{error:step.error}:{result:step.result}})
   }}
  let result
  try{result=await rc022Negotiate(spec.negotiation,{transport,transportKind:spec.transportKind,environment:'node',disposableProbe:spec.disposableProbe,defaultTimeoutMs:10,clientInfo:{name:'dsh-mcp-client',version:'0.0.1'},capabilities:{}})}catch(error){result={error:normalize(error)}}
  const restored={message:transport.onmessage===savedMessage,error:transport.onerror===savedError}
  if(!result.error)await transport.start()
  transport.onclose?.();rc022Disarm(transport);transport.onclose?.()
  rows.push({result,requests,events,starts,restored,closeRestored:transport.onclose===savedClose})
 }
 process.stdout.write(JSON.stringify(rows))
}finally{if(created)fs.unlinkSync(temporary)}
