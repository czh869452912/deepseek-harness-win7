import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'
import {readFileSync,writeFileSync} from 'node:fs'
import {createServer} from 'node:http'
import {fileURLToPath} from 'node:url'
import WebSocket from '../../reference/packages/api/gateway/node_modules/ws/wrapper.mjs'
import {Context} from '@deepseek-ai/cordis'
import {RemoteStreamMuxServer} from '../../reference/packages/api/gateway/src/stream-server.ts'
import {HostConnectionService} from '../../reference/packages/client/connection/src/rpc-host.ts'
import {bridge} from '../../reference/packages/client/connection/src/http-bridge.ts'
import {buildWindow,formatReadOutput} from '../../reference/packages/fs/tool-fs/src/read-render.ts'
import {observeHttp} from './deepseek-http.ts'

const root=fileURLToPath(new URL('../../',import.meta.url))
const outcome=await buildWindow(['\u{1f600}rest'],{offset:1,limit:1,maxLineLength:1,maxBytes:51200},'fixture.txt')
const values=[['high','\ud83d'],['low','\ude00'],['keys',{'\ud83d':'\ude00'}],['pair','\ud83d\ude00'],
  ['astral','\u{1f600}中文'],['ascii','normal'],['read',{outcome,rendered:formatReadOutput('fixture.txt',{offset:1,...outcome})}]] as const
const ctx=new Context()
new HostConnectionService(ctx,[],{isAuthenticated:()=>true} as any)
ctx.connection.rpc.intercept('/api',()=>true,async (_endpoint,payload:any)=>({ok:true,value:payload.args.value}))
const handler=ctx.connection.createSharedFetchHandler('/api')
const mux=new RemoteStreamMuxServer(async (_endpoint,payload:any)=>(async function*(){yield payload.args.value})(),
  error=>({code:'internal',message:String(error),details:{}}),30000)
const server=createServer((request,response)=>{void bridge(request,response,handler)})
server.on('upgrade',(request,socket,head)=>mux.handleUpgrade(request,socket,head))
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
const port=(server.address() as any).port
const socket=new WebSocket(`ws://127.0.0.1:${port}/api/remote.mux`)
await new Promise<void>((resolve,reject)=>{socket.once('open',resolve);socket.once('error',reject)})
const rows:any[]=[]
try{
  for(const [name,value] of values){
    const frames:any[]=[]
    const finished=new Promise<void>((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('Unicode Source mux timed out')),5000)
      const receive=(data:any)=>{
        const text=data.toString('utf8')
        frames.push({text,value:JSON.parse(text)})
        if(frames.length===2){clearTimeout(timer);socket.off('message',receive);resolve()}
      }
      socket.on('message',receive)
    })
    socket.send(JSON.stringify({type:'open',streamId:name,endpoint:'fixture/echo_stream',payload:{args:{value}}}))
    await finished
    rows.push({name:name+'/mux',value:frames})
    const response=await fetch(`http://127.0.0.1:${port}/api/fixture/echo`,{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({type:'client-request',rpcId:name,method:'fixture/echo',payload:{args:{value}}})})
    const text=await response.text()
    rows.push({name:name+'/rpc',value:{status:response.status,text,value:JSON.parse(text)}})
    const observed=await observeHttp({messages:[{role:'user',content:[{type:'text',text:typeof value==='string'?value:JSON.stringify(value)}]}]})
    rows.push({name:name+'/llm',value:observed})
  }
}finally{
  socket.terminate()
  await mux.close()
  await ctx.fiber.dispose()
  server.closeAllConnections()
  await new Promise<void>(resolve=>server.close(()=>resolve()))
}
writeFileSync(process.env.DSH_UNICODE_CARRIER_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',root+'reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  node:process.version,fixtureSha256:createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex'),rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
