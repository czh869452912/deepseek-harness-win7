import { readFileSync } from 'node:fs'
import { connect as tcpConnect } from 'node:net'
import { connect as tlsConnect } from 'node:tls'
import { load } from './rc022_subagent_fixture.mts'
const { Context }=await load('vendor/cordis/src/index.ts'),{default:WebServer}=await load('packages/host/webserver/src/index.ts')
const fixture=JSON.parse(readFileSync(process.argv[3],'utf8'))
async function scenario(secure:boolean,peerEnd:boolean){
 const ctx=new Context(),clients:any[]=[],calls:string[]=[];let ownerClosed:Promise<void>|undefined,owner:any,ended:Promise<void>
 try{
  const fiber=await ctx.plugin(WebServer,{host:'127.0.0.1',port:0,tls:secure?{certFile:fixture.cert,keyFile:fixture.key}:null}),server=ctx.webServer
  server.registerUpgrade({path:'/owned',handler:(_request:any,socket:any)=>{
   calls.push('handler-returned');socket.write('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n')
   owner=socket;ended=new Promise(resolve=>socket.once('end',()=>resolve()))
   socket.on('data',(data:Buffer)=>socket.write(Buffer.concat([Buffer.from('ACK:'),data])))
   ownerClosed=new Promise(resolve=>socket.once('close',()=>resolve()))
  }})
  const socket=secure?tlsConnect({host:'127.0.0.1',port:server.port,ca:readFileSync(fixture.cert)}):tcpConnect({host:'127.0.0.1',port:server.port});clients.push(socket)
  await new Promise<void>((resolve,reject)=>{socket.once(secure?'secureConnect':'connect',resolve);socket.once('error',reject)})
  let received=Buffer.alloc(0);const readers:Array<()=>void>=[]
  socket.on('data',data=>{received=Buffer.concat([received,data]);for(const reader of [...readers])reader()})
  async function consume(length:number){if(received.length<length)await new Promise<void>(resolve=>{const ready=()=>{if(received.length>=length){readers.splice(readers.indexOf(ready),1);resolve()}};readers.push(ready)});const value=received.subarray(0,length);received=received.subarray(length);return value}
  const head='HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n'
  socket.write('GET /owned HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n');const status=Number((await consume(Buffer.byteLength(head))).toString().split(' ')[1])
  await new Promise(resolve=>setTimeout(resolve,20));const replies=[]
  for(const data of ['hello','world']){socket.write(data);replies.push((await consume(9)).toString())}
  const clientClosed=new Promise<void>(resolve=>socket.once('close',()=>resolve()))
  let halfOpen=null;if(peerEnd){socket.end();await ended!;halfOpen=!owner.destroyed}
  await fiber.dispose();await Promise.all([ownerClosed,clientClosed])
  return {secure,peerEnd,status,calls,replies,halfOpen,closed:socket.destroyed,ownerJobsSettled:true,trackedSockets:server.upgradedSockets.size}
 }finally{for(const client of clients)client.destroy();await ctx.fiber.dispose()}
}
const rows=[];for(const [secure,peerEnd] of [[false,false],[true,false],[false,true]])rows.push(await scenario(secure,peerEnd));process.stdout.write(JSON.stringify(rows))
