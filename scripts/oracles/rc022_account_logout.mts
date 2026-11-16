import fs from 'node:fs'
import http from 'node:http'
import {getEventListeners} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const {revokeAccount}=await load('packages/credentials/deepseek-account/src/logout.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],hits:any[]=[],diagnostics:any[]=[],attempts=new Map(),log=console.error
console.error=(label:any,value:any)=>diagnostics.push({label:String(label).replace('[deepseek-account] ',''),...value})
const server=http.createServer(async(req,res)=>{
 for await(const _ of req){}
 const index=Number(req.url!.split('/')[1]),entry=inputs[index],attempt=(attempts.get(index)??0)+1;attempts.set(index,attempt)
 hits.push({path:req.url!.slice(('/'+index).length),token:req.headers['x-dsh-auth-token'],deployment:req.headers['x-deployment']})
 if(entry.mode.startsWith('header-'))return
 res.statusCode=(entry.mode.startsWith('body-')?1:entry.successAt)===attempt?200:503
 const payload='{"code":0,"data":{"biz_code":0,"biz_data":null}}';res.setHeader('content-length',Buffer.byteLength(payload))
 if(entry.mode.startsWith('body-')){res.write('{');return}
 res.end(payload)
})
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
try{
 for(const [index,entry] of inputs.entries()){
  const start=hits.length,logged=diagnostics.length,controller=new AbortController();let timer:any
  if(entry.mode==='pre-abort')controller.abort(new Error('private-cancel'))
  else if(entry.mode.includes('abort'))timer=setTimeout(()=>controller.abort(new Error('private-cancel')),40)
  try{await revokeAccount(`http://127.0.0.1:${(server.address() as any).port}/${index}`,'captured-old-token',
   {maxRetries:entry.maxRetries,delayMs:1,requestTimeoutMs:entry.mode.includes('timeout')?100:1000},controller.signal,{'x-deployment':'base'})}
  finally{clearTimeout(timer)}
  const logs=diagnostics.slice(logged).map(value=>({...value,path:value.path.slice(('/'+index).length)}))
  rows.push({index,hits:hits.slice(start),diagnostics:logs,listeners:getEventListeners(controller.signal,'abort').length})
 }
}finally{console.error=log;server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))}
process.stdout.write(JSON.stringify(rows))
