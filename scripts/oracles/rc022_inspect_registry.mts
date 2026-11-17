import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {CordisInspectRegistryService}=await load('packages/extensions/cordis-host-runner/src/inspect-registry.ts')
const modes=['success','sync-success','timeout','failure-timeout','first-failure','invalid-timeout','invalid-success',
 'wrong-agent-failure','wrong-agent-success','late-success','offline','disconnect','no-gateway',
 'abort','pre-abort','abort-publish','dispose','notify-timeout','notify-dispose','manifest-replace','manifest-empty',
 'omitted','null','host','host-snapshot','publish-throw']
const manifest=()=>({id:'Service',description:'Test Service provider.',methods:[{name:'listService',description:'Inspect one service.',
 inputSchema:{type:'object',properties:{service:{type:'string'}},additionalProperties:false},
 outputSchema:{type:'object',properties:{name:{type:'string'}},required:['name']}}]})
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve()}
const rows:any[]=[]
for(const mode of modes){
 const ctx=new Context(),fiber=ctx.plugin(CordisInspectRegistryService,100);await fiber
 const registry=ctx.cordisInspect;registry.syncClientManifest([manifest()])
 const requests:any[]=[],resolved:any[]=[],logs:any[]=[],acks:any[]=[],tasks:Promise<any>[]=[]
 const controller=new AbortController(),agent:any={id:'owner'},listeners=new Set<any>()
 const add=controller.signal.addEventListener.bind(controller.signal),remove=controller.signal.removeEventListener.bind(controller.signal)
 controller.signal.addEventListener=((name:any,callback:any,options:any)=>{if(name==='abort')listeners.add(callback);return add(name,callback,options)}) as any
 controller.signal.removeEventListener=((name:any,callback:any,options:any)=>{if(name==='abort')listeners.delete(callback);return remove(name,callback,options)}) as any
 let online=mode!=='offline'
 if(mode!=='no-gateway'){ctx.provide('typertGateway');ctx.set('typertGateway',{hasLiveClient:()=>online})}
 ctx.on('cordis/inspect-query',(request:any)=>{requests.push(request)})
 ctx.on('cordis/inspect-query-resolved',(event:any)=>{resolved.push(event.requestId)})
 if(mode.startsWith('notify-'))ctx.on('cordis/inspect-query-resolved',()=>{throw new Error('notify failed')})
 const originalSet=globalThis.setTimeout,originalClear=globalThis.clearTimeout,originalError=console.error
 const timers=new Map<any,()=>void>();let next=0
 globalThis.setTimeout=((callback:any,_delay:any,...args:any[])=>{const id=++next;timers.set(id,()=>callback(...args));return id}) as any
 globalThis.clearTimeout=((id:any)=>{timers.delete(id)}) as any
 console.error=(...args:any[])=>{logs.push([args[0],args[1].message])}
 const fire=()=>{for(const [id,callback] of [...timers]){timers.delete(id);callback()}}
 const result=(promise:Promise<any>)=>promise.then(value=>({value}),error=>({error:error.message}))
 const start=(input:any=undefined)=>{const task=result(registry.query('client','Service','listService',input,agent,controller.signal));tasks.push(task);return task}
 const answer=(data:any={name:'theme'},owner:any=agent)=>registry.resolveClientQuery(owner,requests.at(-1).requestId,{ok:true,data})
 try{
  if(mode==='sync-success')ctx.on('cordis/inspect-query',(request:any)=>{acks.push(registry.resolveClientQuery(agent,request.requestId,{ok:true,data:{name:'sync'}}))})
  if(mode==='abort-publish')ctx.on('cordis/inspect-query',()=>{controller.abort(new Error('fixture abort'))})
  if(mode==='publish-throw')ctx.on('cordis/inspect-query',()=>{throw new Error('publish failed')})
  if(mode==='pre-abort')controller.abort(new Error('fixture abort'))
  if(mode==='host'||mode==='host-snapshot'){
   const data={name:'local'};registry.register({manifest:manifest(),query:()=>data})
   tasks.push(result(registry.query('host','Service','listService',{},agent,controller.signal)))
   if(mode==='host-snapshot')data.name='mutated'
  }else start(mode==='null'?null:undefined)
  const initial={requests:requests.length,timers:timers.size,pending:registry.pending.size}
  if(['success','no-gateway','omitted','null'].includes(mode))acks.push(answer(),answer())
  else if(mode==='failure-timeout'||mode==='first-failure'){
   acks.push(registry.resolveClientQuery(agent,requests.at(-1).requestId,{ok:false,reason:'provider-error',message:'page failed'}))
   if(mode==='first-failure')acks.push(registry.resolveClientQuery(agent,requests.at(-1).requestId,{ok:false,reason:'provider-error',message:'second failure'}))
   fire()
  }else if(mode==='invalid-timeout'||mode==='invalid-success'){
   acks.push(answer({}));if(mode==='invalid-success')acks.push(answer());else fire()
  }else if(mode.startsWith('wrong-agent')){
   const resolution=mode.endsWith('failure')?{ok:false,reason:'provider-error',message:'foreign page'}:{ok:true,data:{name:'foreign'}}
   acks.push(registry.resolveClientQuery({id:'other'},requests.at(-1).requestId,resolution));fire()
  }else if(mode==='timeout'||mode==='notify-timeout')fire()
  else if(mode==='late-success'){fire();acks.push(answer())}
  else if(mode==='disconnect'){online=false;fire()}
  else if(mode==='abort')controller.abort(new Error('fixture abort'))
  else if(mode==='dispose'||mode==='notify-dispose')await fiber.dispose()
  else if(mode==='manifest-replace'||mode==='manifest-empty'){
   const changed:any=manifest();changed.methods[0].outputSchema={type:'object',properties:{next:{type:'string'}},required:['next']}
   registry.syncClientManifest(mode==='manifest-empty'?[]:[changed]);acks.push(answer())
   if(mode==='manifest-replace'){start();acks.push(answer({next:'new'}))}
  }
  await flush()
  rows.push({mode,initial,requests,resolved,acks,results:await Promise.all(tasks),timers:timers.size,pending:registry.pending.size,listeners:listeners.size,logs})
 }finally{
  await fiber.dispose();await flush();globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;console.error=originalError
  await ctx.fiber.dispose()
 }
}
console.log(JSON.stringify(rows))
