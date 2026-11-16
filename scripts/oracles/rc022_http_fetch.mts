import fs from 'node:fs'
import http from 'node:http'
import zlib from 'node:zlib'
import {getEventListeners} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const p=await load('packages/web/web-fetch-http/src/provider.ts')
const plugin=await load('packages/web/web-fetch-http/src/index.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),hits:any[]=[],rows:any[]=[]
const defaults={maxResponseBytes:5000000,maxBodyChars:100000,timeoutMs:30000,maxRedirects:5,userAgent:'paired-fetch/1.0'}
let entered=false
const server=http.createServer((req,res)=>{
 const parts=req.url!.split('/'),index=/^\d+$/.test(parts[1]!)?Number(parts[1]):0,entry=inputs[index],mode=entry.mode
 const redirected=parts.length>2&&parts[2]!.startsWith('next'),headers:any={}
 for(const key of ['user-agent','accept','authorization','cookie'])if(req.headers[key]!==undefined)headers[key]=req.headers[key]
 hits.push({path:req.url,headers});entered=true
 if(['header-abort','header-timeout'].includes(mode))return
 let data=Buffer.from(entry.data??Buffer.from('final body')),status=entry.status??200
 if(mode==='redirect'&&!redirected){res.statusCode=status;if(entry.location!==null)res.setHeader('location',entry.location);res.setHeader('content-length','0');res.end();return}
 if(mode==='redirect'){data=Buffer.from('final body');status=200}
 if(entry.encoding==='gzip')data=zlib.gzipSync(data)
 if(entry.encoding==='deflate')data=zlib.deflateSync(data)
 if(entry.wireSuffixByte!==undefined)data=Buffer.concat([data,Buffer.alloc(entry.wireSuffixCount,entry.wireSuffixByte)])
 res.statusCode=status
 if(entry.contentType!==null)res.setHeader('content-type',entry.contentType??'text/plain')
 if((entry.wireEncoding??entry.encoding)!==undefined)res.setHeader('content-encoding',entry.wireEncoding??entry.encoding)
 if(mode.startsWith('body-')||mode==='dropped-body')res.setHeader('content-length','100')
 else if(entry.declared)res.setHeader('content-length',data.length)
 else res.setHeader('transfer-encoding','chunked')
 if(mode.startsWith('body-')||mode==='dropped-body'){
  res.write('X');if(mode==='dropped-body')setTimeout(()=>res.destroy(),5);return
 }
 res.end([204,205,304].includes(status)?undefined:data)
})
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
const origin=`http://127.0.0.1:${(server.address() as any).port}`
try{
 rows.push({description:new p.HttpFetchProvider(defaults).description,available:new p.HttpFetchProvider(defaults).available()})
 for(const [index,entry]of inputs.entries()){
  const mode=entry.mode,limits={...defaults,...entry.limits}
  if(mode.endsWith('timeout'))limits.timeoutMs=100
  if(mode==='config'){
   limits[entry.key]=entry.value
   try{plugin.apply({web:{registerFetchProvider(){}}},limits);rows.push({ok:true})}catch(error:any){rows.push({message:error.message})}
   continue
  }
  fs.writeFileSync(process.argv[3]!+'.progress.json',JSON.stringify({index,mode}))
  const controller=new AbortController(),start=hits.length;entered=false
  let interval:any,timer:any,result:any
  if(mode==='pre-abort')controller.abort(Error('caller stopped'))
  if(['header-abort','body-abort'].includes(mode))interval=setInterval(()=>{if(entered){clearInterval(interval);timer=setTimeout(()=>controller.abort(Error('caller stopped')),10)}},1)
  try{
   const request={url:entry.url??`${origin}/${index}/start`},operation=new p.HttpFetchProvider(limits).fetch(request,controller.signal)
   if(mode==='snapshot-request')request.url='invalid-after-call'
   result=await operation
  }
  catch(error:any){result={code:error.code??null,message:error.message}}
  finally{clearInterval(interval);clearTimeout(timer)}
  controller.abort(Error('scope disposed'))
  rows.push({result,hits:hits.slice(start),listeners:getEventListeners(controller.signal,'abort').length})
 }
}finally{server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))}
process.stdout.write(JSON.stringify(rows).replaceAll(origin,'http://fixture.test'))
