import {readFile} from 'node:fs/promises'
import {createServer} from 'node:http'
import {once} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{Peer}=await load('packages/client/connection/src/peer.ts'),{RemoteStreamMuxServer}=await load('packages/api/gateway/src/stream-server.ts'),protocol=await load('packages/api/gateway/src/stream-protocol.ts'),{remoteErrorOf}=await load('packages/typert/protocol/src/index.ts'),WebSocket=(await load('packages/api/gateway/node_modules/ws/wrapper.mjs')).default
const data=JSON.parse(await readFile(process.argv[3],'utf8')),rows:any[]=[]
function negativeZero(value:any):boolean{if(typeof value==='number')return Object.is(value,-0);if(value&&typeof value==='object')return Object.values(value).some(negativeZero);return false}
for(const [direction,parse] of [['client',protocol.parseRemoteStreamClientMessage],['server',protocol.parseRemoteStreamServerMessage]] as const){for(const [index,text] of data.messages.entries()){let result:any;try{const value=parse(text);result={value,negativeZero:negativeZero(value)}}catch(error){result={error:(error as Error).message}}rows.push({direction,index,...result})}}
// Obtain the private queue constructor through the actual mux opener contract.
const ctx=new Context(),peer=new Peer(ctx,{principal:{kind:'owner'}}),server=createServer();let captured:any;const opened=new Promise<void>(resolve=>{captured=resolve})
let Inbox:any
const mux=new RemoteStreamMuxServer(async(_endpoint:any,_payload:any,inbox:any,_peer:any,control:any)=>{Inbox=inbox.constructor;captured();return (async function*(){await new Promise<void>(resolve=>{if(control.signal.aborted)resolve();else control.signal.addEventListener('abort',()=>resolve(),{once:true})})})()},(error:any)=>remoteErrorOf(error)??{code:'fixture/error',message:error.message,details:{}},{heartbeatIntervalMs:10000,streamInboxBytes:8,compression:false})
server.on('upgrade',(request,socket,head)=>mux.handleUpgrade(request,socket,head,peer));server.listen(0,'127.0.0.1');await once(server,'listening');const client=new WebSocket('ws://127.0.0.1:'+(server.address() as any).port);await once(client,'open');client.send(JSON.stringify({type:'open',streamId:'capture',endpoint:'fixture/echo',payload:{}}));await opened
function failure(error:any){const remote=remoteErrorOf(error);return remote?{code:remote.code,message:remote.message,details:remote.details}:{message:error.message}}
try{async function read(box:any){try{return await box.next()}catch(error){return {error:failure(error)}}}
 for(const [name,actions] of data.boxes){const violations:any[]=[],box=new Inbox(8,'fixture/echo',(error:any)=>violations.push(failure(error))),results:any[]=[];let pending:any
  for(const [kind,value,bytes] of actions){if(kind==='push')box.push(value,bytes);else if(kind==='end')box.end();else if(kind==='fail')box.fail(new Error(value));else if(kind==='return'){await box.return();results.push({done:true})}else if(kind==='read')results.push(await read(box));else if(kind==='start'){pending=read(box);await Promise.resolve()}else if(kind==='pending')results.push(await pending);else if(kind==='claim'){try{box[Symbol.asyncIterator]();results.push({claimed:true})}catch(error){results.push({error:{message:(error as Error).message}})}}
  }
  rows.push({name,results,violations,bytes:box.bytes});await box.return()
 }
}finally{client.terminate();await mux.close();await new Promise<void>(resolve=>server.close(()=>resolve()));await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
