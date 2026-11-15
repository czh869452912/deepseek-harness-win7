import {createServer} from 'node:http'
import {once} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{Peer}=await load('packages/client/connection/src/peer.ts'),{RemoteStreamMuxServer}=await load('packages/api/gateway/src/stream-server.ts'),{remoteErrorOf}=await load('packages/typert/protocol/src/index.ts'),WebSocket=(await load('packages/api/gateway/node_modules/ws/wrapper.mjs')).default
const rows:any[]=[],cases=['echo','queued','overflow','after-end','cancel','unknown','duplicate','invalid','binary','peer-left','failure','cycle','compression','no-negotiation','heartbeat']
for(const name of cases){
 const ctx=new Context(),server=createServer(),peer=new Peer(ctx,{principal:{kind:'owner'}}),windows:any[]=[];let retired:any,release:any
 const ended=new Promise<void>(resolve=>{retired=resolve}),gate=new Promise<void>(resolve=>{release=resolve})
 const opener=async(endpoint:any,payload:any,uplink:any,trusted:any,control:any,window:any)=>{
  windows.push({endpoint,peer:trusted===peer,window})
  if(name==='queued'&&endpoint==='fixture')await gate
  return (async function*(){try{
   if(endpoint==='barrier'){yield {barrier:true};return}
   yield {ready:true}
   if(['overflow','after-end','duplicate','peer-left','heartbeat'].includes(name)){await new Promise<void>(resolve=>{if(control.signal.aborted)resolve();else control.signal.addEventListener('abort',()=>resolve(),{once:true})});return}
   if(name==='failure')throw new Error('fixture failed')
   if(name==='cycle'){const value:any={};value.cycle=value;yield value;return}
   for await(const value of uplink)yield value
  }finally{retired()}})()
 }
 const failure=(error:any)=>{const remote=remoteErrorOf(error);return remote?{code:remote.code,message:remote.message,details:remote.details}:{code:'fixture/error',message:error.message,details:{}}}
 const mux=new RemoteStreamMuxServer(opener,failure,{heartbeatIntervalMs:name==='heartbeat'?20:10000,streamInboxBytes:['compression','no-negotiation'].includes(name)?8192:200,compression:['compression','no-negotiation'].includes(name)})
 server.on('upgrade',(request,socket,head)=>mux.handleUpgrade(request,socket,head,peer));server.listen(0,'127.0.0.1');await once(server,'listening')
 const client=new WebSocket('ws://127.0.0.1:'+(server.address() as any).port,{perMessageDeflate:name==='compression',autoPong:name!=='heartbeat'}),queue:any[]=[],waiting:any[]=[],frames:any[]=[];let pings=0
 const put=(value:any)=>waiting.length?waiting.shift()(value):queue.push(value)
 client.on('message',(value:any)=>put(JSON.parse(value.toString())));client.on('close',(code:any,reason:any)=>put({closed:code,reason:reason.toString()}));client.on('ping',()=>{pings++});await once(client,'open')
 const flags:boolean[]=[];let wire=Buffer.alloc(0)
 client._socket.on('data',(data:Buffer)=>{wire=Buffer.concat([wire,data]);while(wire.length>=2){let length=wire[1]&127,offset=2;if(length===126||length===127){const count=length===126?2:8;if(wire.length<2+count)return;length=length===126?wire.readUInt16BE(2):Number(wire.readBigUInt64BE(2));offset+=count}if(wire[1]&128)offset+=4;if(wire.length<offset+length)return;if((wire[0]&15)===1)flags.push(Boolean(wire[0]&64));wire=wire.subarray(offset+length)}})
 const send=(value:any)=>client.send(JSON.stringify(value)),take=async()=>{const value=queue.length?queue.shift():await new Promise(resolve=>waiting.push(resolve));frames.push(value);return value}
 try{
  const key='s-中';send({type:'open',streamId:key,endpoint:'fixture',payload:{}})
  if(name==='queued'){
   send({type:'item',streamId:key,value:'queued'});send({type:'end',streamId:key});send({type:'open',streamId:'barrier',endpoint:'barrier',payload:{}})
   await take();await take();release();await take();await take();await take()
  }else{
   await take()
   if(['echo','compression','no-negotiation'].includes(name)){send({type:'item',streamId:key,value:['compression','no-negotiation'].includes(name)?'x'.repeat(4096):'中文'});await take();send({type:'item',streamId:key});await take();send({type:'end',streamId:key});await take()}
   else if(name==='overflow'){send({type:'item',streamId:key,value:'x'.repeat(201)});await take()}
   else if(name==='after-end'){send({type:'end',streamId:key});send({type:'item',streamId:key,value:1});await take()}
   else if(name==='cancel'){send({type:'cancel',streamId:key});await ended;send({type:'open',streamId:'barrier',endpoint:'barrier',payload:{}});await take();await take()}
   else if(name==='unknown'){for(const type of ['item','end','cancel'])send({type,streamId:'unknown'});send({type:'end',streamId:key});await take()}
   else if(name==='duplicate'){send({type:'open',streamId:key,endpoint:'fixture',payload:{}});await take()}
   else if(name==='invalid'){client.send('{');await take()}
   else if(name==='binary'){client.send(Buffer.from('binary'));await take()}
   else if(name==='peer-left'){await peer.dispose();await take()}
   else if(['failure','cycle','heartbeat'].includes(name))await take()
  }
  rows.push({name,frames,windows,compressed:client.extensions.includes('permessage-deflate'),compressedFrames:flags,heartbeatPings:name==='heartbeat'?pings:0})
 }finally{release();client.terminate();await mux.close();await new Promise<void>(resolve=>server.close(()=>resolve()));await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
