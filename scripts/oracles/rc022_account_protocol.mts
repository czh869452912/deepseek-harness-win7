import fs from 'node:fs'
import http from 'node:http'
import zlib from 'node:zlib'
import {load} from './rc022_subagent_fixture.mts'
const account=await load('packages/credentials/deepseek-account/src/protocol.ts')
const details=await load('packages/credentials/deepseek-account/src/details.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),hits:any[]=[],rows:any[]=[],diagnostics:any[]=[],log=console.error
console.error=(label:any,value:any)=>diagnostics.push({label:String(label).replace('[deepseek-account] ',''),...value})
const server=http.createServer(async(req,res)=>{
 const chunks=[];for await(const chunk of req)chunks.push(chunk)
 const data=Buffer.concat(chunks),index=Number(req.url!.split('/')[1]),entry=inputs[index]
 hits.push({path:req.url!.slice(('/'+index).length),method:req.method,auth:req.headers['x-dsh-auth-token']??null,
  deployment:req.headers['x-deployment']??null,contentType:req.headers['content-type']??null,body:data.toString('utf8')})
 const mode=entry.mode??''
 if(mode.startsWith('header-'))return
 const wire=entry.wire;let payload=Buffer.from(JSON.stringify(entry.body))
 if(wire==='bad-json')payload=Buffer.from('not-json')
 else if(wire==='bom')payload=Buffer.concat([Buffer.from([239,187,191]),payload])
 else if(wire==='invalid-utf8')payload=Buffer.concat([Buffer.from('{"code":0,"data":{"biz_code":0,"biz_data":"'),Buffer.from([255]),Buffer.from('"}}')])
 else if(['limit','over-limit','gzip-over-limit'].includes(wire))payload=Buffer.concat([payload,Buffer.alloc(65536-payload.length+(wire==='limit'?0:1),32)])
 if(wire==='gzip-bomb')payload=Buffer.concat([payload,Buffer.alloc(10*1024*1024,32)])
 if(['gzip','gzip-over-limit','gzip-bomb'].includes(wire)){payload=zlib.gzipSync(payload);res.setHeader('content-encoding','gzip')}
 res.statusCode=entry.status??200;if([301,302].includes(res.statusCode))res.setHeader('location','/leaked')
 if(wire==='broken-chunk'){
  res.socket!.write('HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nZ\r\ninvalid\r\n');res.socket!.end();return
 }
 res.setHeader('content-length',payload.length+(wire==='truncated'?10:0))
 if(mode.startsWith('body-')){res.write('{');return}
 if(wire==='truncated'){res.write(payload);res.socket!.end();return}
 res.end(payload)
})
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
try{
 for(const [index,entry] of inputs.entries()){
  const start=hits.length,logged=diagnostics.length;let result:any,timer:any
  try{
   let value:any
   if(entry.kind==='origin')value=account.platformOrigin(entry.value,entry.allow,entry.field)
   else if(entry.kind==='login')value=account.loginOrigin(entry.value)
   else if(entry.kind==='browser')value=account.browserUrl(entry.value,entry.origin,'/dsh/authorize',entry.rewrite)
   else if(entry.kind==='headers')value=account.platformHeaders(entry.value)
   else{
    const origin=`http://127.0.0.1:${(server.address() as any).port}/${index}`,controller=new AbortController(),mode=entry.mode??''
    const reason=new Error('private-cancel');if(mode.includes('timeout'))reason.name='TimeoutError'
    if(mode==='pre-abort')controller.abort(reason)
    else if(mode)timer=setTimeout(()=>controller.abort(reason),40)
    const signal=controller.signal,headers={'x-deployment':'base'}
    if(entry.op==='platform')value=await account.requestPlatform(origin,'auth_init',{verifier:'request-secret'},signal,headers)
    else if(entry.op==='account')value=await account.requestAccount(origin,'/auth-api/v0/users/current','fixture-token',signal,headers)
    else if(entry.op==='notifications')value=await account.requestNotifications(origin,'fixture-token',signal,headers)
    else if(entry.op==='content')value=await account.requestNotificationContent(origin,'fixture-token',"a +/!~*'()雪?",signal,headers)
    else if(entry.op==='event')value=await account.requestNotificationEvent(origin,'fixture-token','id','dismissed',signal,headers)
    else if(entry.op.startsWith('detail-'))value=await details.readAccountDetail(entry.op.slice(7),origin,'fixture-token',signal,headers)
    else value=await account.logoutAccount(origin,'fixture-token',signal,headers)
   }
   result={value:value===undefined?'<undefined>':value}
  }catch(error:any){result={error:{message:error.message,code:error.code??null,unauthorized:error instanceof account.AccountUnauthorizedError}}}
  finally{clearTimeout(timer)}
  const logs=diagnostics.slice(logged).map(value=>JSON.parse(JSON.stringify(value)))
  if(entry.kind==='http')for(const value of logs)if(value.path!==undefined)value.path=value.path.slice(('/'+index).length)
  rows.push({index,result,hits:hits.slice(start),diagnostics:logs})
 }
}finally{console.error=log;server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))}
process.stdout.write(JSON.stringify(rows))
