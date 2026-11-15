import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Registry=(await load('packages/typert/registry/src/index.ts')).default,Access=(await load('packages/api/remote-access/src/index.ts')).default,Gateway=(await load('packages/api/gateway/src/index.ts')).default
const {Remote,TypertRemoteService}=await load('packages/typert/protocol/src/index.ts'),{HostConnectionService}=await load('packages/client/connection/src/rpc-host.ts')
const cases=['plain','root-bytes','nested-bytes','empty-bytes','undefined','null','failure','empty-attachments','bad-json','bad-media','bad-method','mismatch','missing-payload','bad-envelope','throws','peer'],rows:any[]=[]
for(const name of cases){const ctx=new Context(),transport=new Context();await ctx.plugin(Registry);await ctx.plugin(Access);await ctx.plugin(Gateway)
 class Fixture extends TypertRemoteService{constructor(child:any){super(child,'fixture')}@Remote value(){return ({plain:{text:'中文'},'root-bytes':new Uint8Array([0,128,255]),'nested-bytes':{'a.b/c':[new TextEncoder().encode('01234').subarray(1,4),{data:new TextEncoder().encode('xy')}]},'empty-bytes':new Uint8Array(),undefined:undefined,null:null} as any)[name]}}
 try{await ctx.plugin(Fixture);await transport.plugin((child:any)=>{new HostConnectionService(child,[],{} as any)});const connection=transport.connection,peer=connection.browserPeer,seen:any[]=[]
  const body:any={type:'client-request',rpcId:'request',method:'fixture/value',payload:{args:{}}}
  if(name==='peer')body.payload.peer={principal:{kind:'forged'}}
  if(name==='mismatch')body.method='other/run'
  if(name==='missing-payload')delete body.payload
  if(name==='bad-envelope'){delete body.type;delete body.method;delete body.payload;body.rpcId='known'}
  const request=new Request('http://localhost/api/fixture/value',{method:name==='bad-method'?'GET':'POST',headers:{'content-type':name==='bad-media'?'text/plain':'Application/JSON; charset=utf-8'},...(name==='bad-method'?{}:{body:name==='bad-json'?'{':JSON.stringify(body)})})
  connection.rpc.intercept('/api',()=>true,async(endpoint:any,payload:any,signal:any,trusted:any)=>{
   seen.push({endpoint,peer:trusted===peer,signal:signal===request.signal,payload})
   if(name==='throws')throw new Error('boom')
   if(name==='failure')return {ok:false,error:{code:'fixture/no',message:'no',details:{}}}
   if(name==='empty-attachments')return {ok:true,value:2,attachments:[]}
   if(name==='peer')return {ok:true,value:trusted.principal}
   return ctx.typertGateway.invokeRpc(endpoint,payload,signal,trusted)
  })
  const response=await connection.createSharedFetchHandler('/api').fetch(request,peer),media=response.headers.get('content-type')!.split(';')[0];let result:any
  if(media==='multipart/form-data'){const form=await response.formData(),parts:any[]=[];for(const [key,value] of form){if(key!=='metadata'){const file=value as File;parts.push({name:key,filename:file.name,type:file.type,bytes:[...new Uint8Array(await file.arrayBuffer())]})}}result={status:response.status,media,metadata:JSON.parse(form.get('metadata') as string),parts}}
  else result={status:response.status,media:media==='application/json'?'json':'text',body:media==='application/json'?await response.json():await response.text()}
  rows.push({name,response:result,seen})
 }finally{await transport.fiber.dispose();await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
