import {readFileSync} from 'node:fs'
import {request as httpsRequest} from 'node:https'
import {request as httpRequest} from 'node:http'
import {connect as tcpConnect} from 'node:net'
import {connect as tlsConnect} from 'node:tls'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),web=await load('packages/host/webserver/src/index.ts'),WebServer=web.default,fixture=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],ctx=new Context(),clients:any[]=[]
for(const host of fixture.hosts){const row:any={name:'bind:'+host,wildcard:web.isWildcardHost(host),loopback:web.isLoopbackHost(host)};try{row.config=WebServer.Config({host,port:0}).host}catch(error:any){row.error=error.message.slice(error.message.indexOf('webserver:'))}try{row.normalized=web.normalizeBindAddress(host)}catch{row.normalized=null}row.urlHost=web.bindUrlHost(host)??null;rows.push(row)}
try{
 const unbound=new Context();try{new WebServer(unbound,WebServer.Config({host:'127.0.0.1',port:0})).getOrigin()}catch(error:any){rows.push({name:'origin-before-bind',error:error.message})}finally{await unbound.fiber.dispose()}
 const fiber=await ctx.plugin(WebServer,{host:'127.0.0.1',port:0,tls:{certFile:fixture.cert,keyFile:fixture.key}});let server=ctx.webServer
 const register=()=>server.register({kind:'exact',path:'/tls',resource:async()=>new Response('SECURE')});register()
 const ca=readFileSync(fixture.cert)
 function get(trust:any=ca):Promise<any>{return new Promise((resolve,reject)=>{const req=(trust===null?httpRequest:httpsRequest)({hostname:'127.0.0.1',port:server.port,path:'/tls',ca:trust===null?undefined:trust,agent:false},res=>{const chunks:Buffer[]=[];res.on('data',data=>chunks.push(Buffer.from(data)));res.on('end',()=>resolve({status:res.statusCode,body:Buffer.concat(chunks).toString()}));res.on('error',reject)});req.on('error',reject);req.end()})}
 function connect(secure:boolean):Promise<any>{return new Promise((resolve,reject)=>{const socket=secure?tlsConnect({host:'127.0.0.1',port:server.port,ca}):tcpConnect({host:'127.0.0.1',port:server.port});clients.push(socket);socket.once(secure?'secureConnect':'connect',()=>resolve(socket));socket.once('error',reject)})}
 rows.push({name:'trusted-tls',protocol:server.protocol,origin:server.getOrigin().replace(String(server.port),'PORT'),response:await get()})
 try{await get(Buffer.alloc(0))}catch{rows.push({name:'untrusted-tls',rejected:true})}
 try{await get(null)}catch{rows.push({name:'plaintext-to-tls',rejected:true})}
 const raw=await connect(false),rawClosed=new Promise(resolve=>raw.once('close',()=>resolve(true)))
 rows.push({name:'parallel-handshake',response:await get()})
 const idle=await connect(true),idleClosed=new Promise(resolve=>idle.once('close',()=>resolve(true)))
 server.registerUpgrade({path:'/upgrade',handler:(_req:any,socket:any)=>socket.write('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n')})
 const up=await connect(true),upClosed=new Promise(resolve=>up.once('close',()=>resolve(true)))
 const header=new Promise<string>((resolve,reject)=>{let value='';up.on('data',(data:any)=>{value+=data.toString();if(value.includes('\r\n\r\n'))resolve(value)});up.on('error',reject)});up.write('GET /upgrade HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n')
 rows.push({name:'tls-upgrade',status:Number((await header).split(' ')[1])});await fiber.dispose();rows.push({name:'tls-unload',closed:await Promise.all([rawClosed,idleClosed,upClosed])})
 try{await connect(true)}catch{rows.push({name:'listener-retired',rejected:true})}
 const plain=await ctx.plugin(WebServer,{host:'127.0.0.1',port:0,tls:null});server=ctx.webServer;register();rows.push({name:'null-tls',protocol:server.protocol,response:await get(null)});await plain.dispose()
}finally{for(const socket of clients)socket.destroy();await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
