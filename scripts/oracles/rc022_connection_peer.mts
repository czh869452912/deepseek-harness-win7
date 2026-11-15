import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{BrowserAuth}=await load('packages/client/connection/src/browser-auth.ts'),{HostConnectionService}=await load('packages/client/connection/src/rpc-host.ts')
const ctx=new Context(),rows:any[]=[];ctx.provide('webServer');ctx.set('webServer',{host:'10.1.2.3',protocol:'https:'});const auth=new BrowserAuth(ctx,Buffer.from(Array.from({length:32},(_,i)=>i)),1),token=new URL(auth.authenticatedUrl('https://localhost')).searchParams.get('token')
const service=await ctx.plugin((child:any)=>{new HostConnectionService(child,['remote.example'],auth)}),connection=ctx.connection
function request(cookie?:string,host='localhost:443'){return {method:'GET',url:'/',headers:{host,...(cookie?{cookie}:{})}}}
function response(){const state:any={status:null,headers:{},body:''};return {state,value:{writeHead(status:any,headers:any){state.status=status;state.headers=headers??{}},end(body:any){state.body=body??''}}}}
function state(admission:any){if('rejection'in admission)return {rejection:admission.rejection};const peer=admission.peer;return {browser:peer===connection.browserPeer,kind:peer.principal.kind,interactions:peer.interactions}}
try{
 rows.push({name:'fences',unknown:state(connection.admit(request())),untrusted:state(connection.admit(request(undefined,'evil'))),bind:connection.isTrusted(request(undefined,'10.1.2.3:9000')),remote:connection.allowsRemoteAuthorities})
 let writer=response();connection.authorizeIndex({...request(),url:'/?token='+token},writer.value);const browser=writer.state.headers['set-cookie'].split(';')[0],browserReq=request(browser)
 rows.push({name:'browser',status:writer.state.status,admission:state(connection.admit(browserReq))})
 const cookies:any[]=[],peers:any[]=[]
 for(const mode of ['none','answer']){writer=response();connection.authorizeConnect({...request(),url:'/connect?token='+token+'&interactions='+mode},writer.value);const cookie=writer.state.headers['set-cookie'].split(';')[0];cookies.push(cookie);const admission=connection.admit(request(cookie));peers.push(admission.peer);rows.push({name:'api-'+mode,status:writer.state.status,admission:state(admission),same:connection.admit(request(cookie)).peer===admission.peer})}
 rows.push({name:'independent',distinct:peers[0]!==peers[1],browser:peers.every(peer=>peer!==connection.browserPeer)})
 const first=connection.admitConnection(request(cookies[0])),second=connection.admitConnection(request(cookies[0]));rows.push({name:'claim',first:state(first),second:state(second),http:state(connection.admit(request(cookies[0])))})
 const pending=first.release(),same=first.release()===pending,revoked=state(connection.admit(request(cookies[0])));await pending;rows.push({name:'release',same,revoked,aborted:peers[0].signal.aborted})
 for(let i=0;i<2;i++)await connection.admitConnection(browserReq).release();rows.push({name:'browser-release',aborted:connection.browserPeer.signal.aborted,admission:state(connection.admit(browserReq))})
 let guest:any,principal:any
 const owner=await ctx.plugin({inject:['connection'],apply(child:any){principal={kind:'guest'};guest=child.connection.createPeer({principal,interactions:'none'});child.connection.fetch.register({path:'/api/fixture/value',methods:['GET'],requestBody:'streaming',fetch:()=>new Response('exact',{status:202})});child.connection.rpc.intercept('/api',()=>true,async(endpoint:any,payload:any,signal:any,peer:any)=>({ok:true,value:{kind:peer.principal.kind,same:peer===guest}}))}})
 const api=connection.createSharedFetchHandler('/api'),req=new Request('https://localhost/api/fixture/value'),ownerResult=await api.fetch(req,connection.browserPeer),guestResult=await api.fetch(req,guest),rpc=await api.fetch(new Request(req.url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type:'client-request',rpcId:'id',method:'fixture/value',payload:{args:{},peer:{kind:'owner'}}})}),guest)
 rows.push({name:'routes',owner:ownerResult.status,guest:guestResult.status,mode:api.requestBodyMode({method:req.method,url:new URL(req.url)}),rpc:await rpc.json(),principal:guest.principal===principal})
 await owner.dispose();rows.push({name:'caller-unload',peer:guest.signal.aborted,route:(await api.fetch(req,connection.browserPeer)).status,mode:api.requestBodyMode({method:req.method,url:new URL(req.url)})})
 await service.dispose();writer=response();connection.authorizeConnect({...request(undefined,'evil'),url:'/connect'},writer.value);rows.push({name:'service-unload',browser:connection.browserPeer.signal.aborted,operator:peers[1].signal.aborted,admission:state(connection.admit(request(cookies[1]))),untrusted:state(connection.admit(request(undefined,'evil'))),connect:writer.state.status})
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
