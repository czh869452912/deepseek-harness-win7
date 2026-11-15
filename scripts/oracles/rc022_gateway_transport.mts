import {request as httpRequest} from 'node:http'
import {once} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Registry=(await load('packages/typert/registry/src/index.ts')).default,Access=(await load('packages/api/remote-access/src/index.ts')).default,Gateway=(await load('packages/api/gateway/src/index.ts')).default,Connection=await load('packages/client/connection/src/index.ts'),WebServer=(await load('packages/host/webserver/src/index.ts')).default,{RecordCredentials}=await load('packages/client/connection/tests/browser-credentials.ts'),{Remote,TypertRemoteService}=await load('packages/typert/protocol/src/index.ts'),{z}=await load('node_modules/zod/index.js'),WebSocket=(await load('packages/api/gateway/node_modules/ws/wrapper.mjs')).default
const ctx=new Context(),readyCallbacks:any[]=[],rows:any[]=[];ctx.provide('credentials',new RecordCredentials());ctx.provide('appReady',{onReady(callback:any){readyCallbacks.push(callback);return ()=>{const index=readyCallbacks.indexOf(callback);if(index>=0)readyCallbacks.splice(index,1)}}})
await ctx.plugin(Registry);await ctx.plugin(Access);const gateway=await ctx.plugin(Gateway,{streamInboxBytes:512,websocketCompression:'none'})
let retired:any,release:any,hold=false;const closed=new Promise<void>(resolve=>{retired=resolve}),released=new Promise<void>(resolve=>{release=resolve})
class Fixture extends TypertRemoteService{
 constructor(child:any){super(child,'fixture')}
 @Remote info(){return {data:new TextEncoder().encode('abc')}}
 @Remote({mode:'stream'}) async *echo(signal:AbortSignal){try{const invocation=this.ctx.invocation;yield {ready:true,kind:invocation.peer.principal.kind,interactions:invocation.peer.interactions,window:invocation.uplinkWindow};for await(const value of invocation.uplink())yield {echo:value,signal:signal===invocation.signal}}finally{if(hold){retired();await released}}}
}
await ctx.plugin(Fixture);ctx.typert.register({package:'fixture',face:'host',model:{},schemas:[],invocations:[{id:'fixture#echo',service:'fixture',namespace:'fixture',method:'echo',mode:'stream',parameters:[],cancellation:{parameter:'signal'},invocation:{kind:'direct'},result:{mode:'src-json'},uplink:{codec:{mode:'strict',typeSymbol:'Number',create:()=>z.number()}}}]})
await ctx.plugin(Connection);await ctx.plugin(WebServer,{host:'127.0.0.1',port:0});const server=ctx.webServer,connection=ctx.connection;let client:any
function http(path:string,body?:any,cookie?:string,upgrade=false,host?:string):Promise<any>{return new Promise((resolve,reject)=>{
 const headers:any={host:host??'127.0.0.1:'+server.port,connection:upgrade?'Upgrade':'close'};if(cookie)headers.cookie=cookie;if(upgrade)Object.assign(headers,{upgrade:'websocket','sec-websocket-version':'13','sec-websocket-key':'AAAAAAAAAAAAAAAAAAAAAA=='})
 const data=body===undefined?undefined:JSON.stringify(body);if(data!==undefined)Object.assign(headers,{'content-type':'application/json','content-length':Buffer.byteLength(data)})
 const req=httpRequest({hostname:'127.0.0.1',port:server.port,path,method:body===undefined?'GET':'POST',headers},response=>{const chunks:Buffer[]=[];response.on('data',data=>chunks.push(Buffer.from(data)));response.on('end',()=>resolve({status:response.statusCode,headers:response.headers,body:Buffer.concat(chunks)}));response.on('error',reject)});req.on('error',(error:any)=>{if(upgrade&&error.code==='ECONNRESET')resolve({status:'closed',headers:{},body:Buffer.alloc(0)});else reject(error)});req.on('upgrade',(res,socket)=>{socket.destroy();resolve({status:res.statusCode,headers:res.headers,body:Buffer.alloc(0)})});req.end(data)
})}
async function unary(cookie:string){return http('/api/fixture/info',{type:'client-request',rpcId:'id',method:'fixture/info',payload:{args:{}}},cookie)}
async function binary(raw:any){const response=new Response(raw.body,{status:raw.status,headers:{'content-type':raw.headers['content-type']}}),form=await response.formData(),parts:any[]=[];for(const [name,value] of form){if(name!=='metadata'){const file=value as File;parts.push({name,filename:file.name,type:file.type,bytes:[...new Uint8Array(await file.arrayBuffer())]})}}return {status:raw.status,media:'multipart/form-data',metadata:JSON.parse(form.get('metadata') as string),parts}}
const queue:any[]=[],waiting:any[]=[]
async function connect(cookie:string){client=new WebSocket('ws://127.0.0.1:'+server.port+'/api/remote.mux',{headers:{cookie},perMessageDeflate:false});client.on('message',(data:any)=>{const value=JSON.parse(data.toString());if(waiting.length)waiting.shift()(value);else queue.push(value)});await once(client,'open')}
function receive():Promise<any>{return queue.length?Promise.resolve(queue.shift()):new Promise(resolve=>waiting.push(resolve))}
const send=(value:any)=>client.send(JSON.stringify(value))
try{
 rows.push({name:'readiness',before:(await http('/api/remote.mux',undefined,undefined,true)).status});for(const callback of [...readyCallbacks])callback()
 rows.push({name:'upgrade-fences',unknown:(await http('/api/remote.mux',undefined,undefined,true)).status,untrusted:(await http('/api/remote.mux',undefined,undefined,true,'evil.example')).status})
 const token=new URL(connection.authenticatedUrl('http://localhost')).searchParams.get('token'),exchanged=await http('/connect?token='+token),cookie=exchanged.headers['set-cookie'][0].split(';')[0]
 rows.push({name:'http-binary',response:await binary(await unary(cookie))});await connect(cookie)
 rows.push({name:'socket-claim',duplicate:(await http('/api/remote.mux',undefined,cookie,true)).status,http:(await unary(cookie)).status})
 send({type:'open',streamId:'good-中',endpoint:'fixture/echo',payload:{args:{}}});let frames=[await receive()];send({type:'item',streamId:'good-中',value:7});frames.push(await receive());send({type:'end',streamId:'good-中'});frames.push(await receive());rows.push({name:'strict-good',frames})
 send({type:'open',streamId:'bad',endpoint:'fixture/echo',payload:{args:{}}});frames=[await receive()];send({type:'item',streamId:'bad',value:'bad'});frames.push(await receive());rows.push({name:'strict-bad',frames})
 hold=true;send({type:'open',streamId:'held',endpoint:'fixture/echo',payload:{args:{}}});await receive();client.terminate();client=undefined;await closed
 while(connection.admit({headers:{host:'127.0.0.1:'+server.port,cookie}}).rejection!==401)await new Promise(resolve=>setImmediate(resolve))
 rows.push({name:'revoked-before-retirement',upgrade:(await http('/api/remote.mux',undefined,cookie,true)).status,held:true});release();await gateway.dispose()
 const fresh=await http('/connect?token='+token),freshCookie=fresh.headers['set-cookie'][0].split(';')[0]
 rows.push({name:'unloaded',upgrade:(await http('/api/remote.mux',undefined,freshCookie,true)).status,rpc:(await unary(freshCookie)).status})
}finally{release();client?.terminate();await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
