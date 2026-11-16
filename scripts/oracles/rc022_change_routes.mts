import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const Deliverables=await load('packages/client/ui-deliverables/src/index.ts')
const {HostConnectionService}=await load('packages/client/connection/src/index.ts')
const {FsError}=await load('packages/fs/fs/src/index.ts')
const {RemoteError}=await load('packages/typert/protocol/src/index.ts')
const cases=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows=[]
for(const test of cases){
 const ctx=new Context(),controller=new AbortController(),calls:any[]=[]
 let pendingStarted:()=>void
 const started=new Promise<void>(resolve=>{pendingStarted=resolve})
 function fail(stage:string){if(test.failure!==stage)return;if(test.remoteCode)throw new RemoteError(test.remoteCode,'/private/host/path',{});throw new FsError('/private/host/path','UNEXPECTED')}
 try{
  ctx.provide('sessionQuery',{readEvent:async(request:any)=>{calls.push({op:'read',request});return{session:{cwd:'/child'},target:{type:'deliverables/presented',data:{turn:1,callId:'call',files:[{path:'output.txt'}]}}}}})
  ctx.provide('workspaceFiles',{stat:async(scope:any,path:string)=>{calls.push({op:'stat',scope,path});fail('stat');if(test.abortDuring)controller.abort(new Error('cancelled'));return{absolutePath:'/host/current.txt'}}})
  ctx.provide('workspaceChanges',{
   summary:(sessionId:string,seq:number)=>{calls.push({op:'summary',sessionId,seq});return test.missing?undefined:{turn:1,cwd:'/secret/workspace',files:[{path:'output.txt',display:'output.txt',added:1,deleted:0}],total:1,added:1,deleted:0,snapshot:{before:'private-before',after:'private-after'}}},
   diff:async(sessionId:string,seq:number,index:number,signal:AbortSignal)=>{calls.push({op:'diff',sessionId,seq,index});fail('diff');if(test.pending){pendingStarted!();await new Promise<void>(resolve=>signal.addEventListener('abort',()=>resolve(),{once:true}));signal.throwIfAborted()}return test.missing||index!==0?undefined:{kind:test.kind??'text',path:'output.txt',display:'output.txt'}}
  })
  ctx.provide('sandboxPolicy',{workspaceRoot:'/fallback'})
  ctx.provide('fs',{resolve:async(path:string)=>{calls.push({op:'resolve',path});return{}},processPathFromHostPath:(path:string)=>{calls.push({op:'mapping',path});return test.unmapped?undefined:'/process/current.txt'},processPath:()=>test.wrongMapping?'/host/wrong':'/host/current.txt'})
  ctx.provide('sessionController',{workspaceDesktop:()=>({name:'host',available:!test.unavailable,fileManager:'explorer'}),openWorkspacePath:async(request:any)=>{calls.push({op:'open',request});fail('open')},workspacePathApplications:async(request:any)=>{calls.push({op:'applications',request});fail('applications');return{applications:[{id:'custom.app',name:'Editor'}]}}})
  const connection=new HostConnectionService(ctx,[],{}),fiber=await ctx.plugin(Deliverables)
  const peer=test.nonOwner?connection.createPeer({principal:{kind:'external'}}):connection.browserPeer
  if(test.aborted)controller.abort(new Error('cancelled'))
  const route=test.path,query=(test.query??'?sessionId=s&seq=7&index='+(test.index??0))+(test.suffix??'')
  async function fetch(){try{const result=await connection.createSharedFetchHandler('/api').fetch(new Request('http://localhost'+route+query,{method:test.method??'GET',signal:controller.signal}),peer);return{status:result.status,headers:Object.fromEntries(result.headers),body:result.status===204?null:result.headers.get('content-type')?.startsWith('application/json')?await result.json():await result.text()}}catch(error:any){return{error:error.message}}}
  let response
  if(test.pending){const pending=fetch();const outcome=await Promise.race([started.then(()=>({started:true})),pending.then(value=>({value}))]);if('value'in outcome)throw new Error('Pending comparison did not start: '+JSON.stringify({outcome,calls}));await fiber.dispose();response=await pending}else{response=await fetch();await fiber.dispose()}
  const after=await connection.createSharedFetchHandler('/api').fetch(new Request('http://localhost/api/present.host'),connection.browserPeer)
  // Native observer additionally checks its explicit platform subscriptions;
  // Node's AbortSignal.any uses weak internal subscriptions, not user listeners.
  rows.push({name:test.name,response,calls,withdrawn:after.status===404,listeners:0})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
