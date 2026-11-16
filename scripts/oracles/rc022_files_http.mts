import fs from 'node:fs'
import http from 'node:http'
import zlib from 'node:zlib'
import {load} from './rc022_subagent_fixture.mts'
const {DeepSeekFilesClient}=await load('packages/llm/llm-deepseek/src/files-api.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),hits:any[]=[],rows:any[]=[]
const server=http.createServer(async(req,res)=>{
 const chunks=[];for await(const chunk of req)chunks.push(chunk)
 const data=Buffer.concat(chunks),index=Number(req.url!.split('/')[1]),entry=inputs[index]
 const hit:any={path:req.url!.slice(('/'+index).length),method:req.method,auth:req.headers['x-api-key'],version:req.headers['anthropic-version'],beta:req.headers['anthropic-beta'],ua:req.headers['user-agent']}
 if(data.length){
  const boundary=req.headers['content-type']!.split('boundary=')[1]!
  hit.fields=data.toString('latin1').split('--'+boundary).slice(1,-1).map(part=>{
   const split=part.indexOf('\r\n\r\n');return{header:Buffer.from(part.slice(2,split),'latin1').toString('utf8'),data:Buffer.from(part.slice(split+4,-2),'latin1').toString('base64')}
  })
 }
 hits.push(hit)
 let body=Buffer.from(typeof entry.body==='string'?entry.body:JSON.stringify(entry.body))
 if(entry.gzip){body=zlib.gzipSync(body);res.setHeader('content-encoding','gzip')}
 res.statusCode=entry.status??200;if(res.statusCode===302)res.setHeader('location','/leaked')
 res.setHeader('content-length',body.length);res.end(body)
})
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
try{
 for(const [index,entry] of inputs.entries()){
  const client=new DeepSeekFilesClient({baseURL:`http://127.0.0.1:${(server.address() as any).port}/${index}/anthropic`,headers:{'X-API-Key':' test-secret ','Anthropic-Version':'wrong','User-Agent':'paired/1'}})
  const start=hits.length;let result:any
  try{
   let value:any
   if(entry.op==='upload')value=await client.upload({data:new Uint8Array([0,1,255]),mediaType:'image/png',filename:'a"\r\nb.png',expiresAfterSeconds:entry.expiry})
   else if(entry.op==='list')value=await client.list()
   else if(entry.op==='list-query')value=await client.list({after:'a +/雪',limit:7})
   else if(entry.op==='delete')value=await client.delete('file-a')
   else value=await client.retrieve(entry.op==='encoded'?"a/!~*'()雪?":'file-a')
   result={value:value??null}
  }catch(error:any){result={error:{message:error.message.replace(`http://127.0.0.1:${(server.address() as any).port}`,'<origin>'),code:error.code??null,status:error.failure?.status??null,detail:error.detail??null}}}
  rows.push({index,result,hits:hits.slice(start)})
 }
}finally{server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))}
process.stdout.write(JSON.stringify(rows))
