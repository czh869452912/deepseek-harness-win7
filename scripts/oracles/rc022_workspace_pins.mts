import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Workspace}=await load('packages/workspace/workspace/src/index.ts'),{workspaceDomainState}=await load('packages/workspace/workspace/src/spec.ts'),{JsonStorageBackend}=await load('packages/storage/storage-json/src/index.ts'),{DomainFacility}=await load('packages/storage/storage-domain/src/index.ts')
const {files}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],trace:any[]=[],changes:any[]=[],live=new Map([['live',{header:{id:'live',createdAt:1}}]]),stored=[{id:'stored',createdAt:0}]
async function boot(){
 const ctx=new Context(),backend=new JsonStorageBackend(join(files,'source'));ctx.provide('storage',{backend:{get:()=>backend}} as any)
 const facility=new DomainFacility(ctx,{backend:'fixture'});ctx.provide('storageDomain',facility)
 ctx.provide('sessionPersistence',{list:async()=>stored.map(header=>({header,revision:'revision'}))} as any);ctx.provide('sessions',{get:(id:string)=>live.get(id),list:()=>[...live.values()]} as any)
 await ctx.plugin(Workspace)
 ctx.on('domain/changed',(change:any)=>{if(change.table==='')changes.push(change.value)})
 ctx.on('workspace/session-activity',(request:any,next:any)=>{trace.push(['activity',request.sessionId]);return request.sessionId==='live'?[{kind:'turn'}]:next()})
 ctx.on('workspace/session-stop',(request:any)=>{trace.push(['stop',request.sessionId,[...ctx.workspaceRegistry.archivedSessionIds],[...ctx.workspaceRegistry.pinnedSessionIds]])})
 ctx.on('workspace/session-archived',(request:any)=>{trace.push(['archived',request.sessionId])})
 ctx.on('workspace/session-unarchiving',(request:any)=>{trace.push(['unarchiving',request.sessionId])})
 return {ctx,backend,facility}
}
let host=await boot();const close=async()=>{await host.ctx.fiber.dispose();await host.facility.closeAll();await host.backend.close()}
try{
 const step=async(name:string,work:any)=>{const before=changes.length,start=trace.length;let error:any;try{await work()}catch(exc:any){error={name:exc.name??'Error',message:exc.message,...(exc.activity===undefined?{}:{activity:exc.activity})}}const registry=host.ctx.workspaceRegistry;rows.push({step:name,pinned:[...registry.pinnedSessionIds],archived:[...registry.archivedSessionIds],changes:changes.length-before,trace:trace.slice(start),...(error===undefined?{}:{error})})}
 let registry=host.ctx.workspaceRegistry
 for(const [name,work] of [['pin-live',()=>registry.pinSession('live')],['pin-stored',()=>registry.pinSession('stored')],['repeat-pin',()=>registry.pinSession('live')],['unknown-pin',()=>registry.pinSession('missing')],['active-archive',()=>registry.archiveSession('live')],['stop-archive',()=>registry.archiveSession('live',{stopActivity:true})],['repeat-archive',()=>registry.archiveSession('live',{stopActivity:true})],['archived-pin',()=>registry.pinSession('live')],['unknown-archive',()=>registry.archiveSession('missing')],['unarchive',()=>registry.unarchiveSession('live')],['repeat-unarchive',()=>registry.unarchiveSession('gone')],['unpin-unknown',()=>registry.unpinSession('gone')],['pin-again',()=>registry.pinSession('live')],['archive-stored',()=>registry.archiveSession('stored')]] as const)await step(name,work)
 await close();host=await boot();registry=host.ctx.workspaceRegistry
 await step('cold-reopen',async()=>{});await step('unpin',()=>registry.unpinSession('live'));await step('clear-archive',()=>registry.unarchiveSession('stored'))
}finally{await close()}
for(const patch of [{},{pinnedSessionIds:['x']},{pinnedSessionIds:[7]},{archivedSessionIds:null},{defaultWorkspaceId:'held'},{defaultWorkspaceId:null},{pendingMutation:{operation:'create',workspaceId:'w',extra:true}},{pendingMutation:null}]){const input={initialized:true,workspaceIds:[],...patch};let answer:any;try{answer={value:workspaceDomainState.parse(input)}}catch{answer={rejected:true}}rows.push({step:'schema',input,...answer})}
console.log(JSON.stringify(rows))
