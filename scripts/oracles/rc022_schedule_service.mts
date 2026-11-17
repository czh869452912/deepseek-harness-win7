import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {ScheduleService}=await load('packages/schedule/schedule/src/index.ts')
const {scheduleTaskSchema}=await load('packages/schedule/schedule/src/storage.ts')
const {JsonStorageBackend}=await load('packages/storage/storage-json/src/index.ts')
const {DomainFacility}=await load('packages/storage/storage-domain/src/index.ts')
const {files}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],trace:any[]=[],changes:any[]=[],agents=new Map<string,any>()
const NativeDate=Date,NOW=NativeDate.parse('2026-09-16T00:00:00Z')
globalThis.Date=class extends NativeDate{constructor(value?:any){super(value===undefined?NOW:value)}static now(){return NOW}} as any
function normalize(value:any){
 const identities=new Map<string,string>()
 const text=(value:string)=>value.replace(/(schedule-|session-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g,(key,prefix)=>{
  prefix=prefix??'message-';if(!identities.has(key))identities.set(key,prefix+(1+[...identities.values()].filter(value=>value.startsWith(prefix)).length));return identities.get(key)!
 })
 const visit=(value:any):any=>typeof value==='string'?text(value):Array.isArray(value)?value.map(visit):value!==null&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,value])=>[text(key),visit(value)])):value
 return visit(JSON.parse(JSON.stringify(value)))
}
const ctx=new Context()
for(const [id,status,depth] of [['actor','idle',0],['target','running',0],['editor','idle',0],['child','idle',1]] as const){
 agents.set(id,{id,status,options:{subagentDepth:depth},session:{id,header:{delegationDepth:depth}},inject:(message:any)=>trace.push(['inject',id,message])})
}
const stat=async(id:string)=>{trace.push(['stat',id]);if(id==='inspect-error')throw new Error('stat refused');if(id==='missing'||id.startsWith('session-'))return undefined;return {header:{delegationDepth:id==='stored-child'?1:0}}}
ctx.provide('agents',{get:(id:string)=>agents.get(id),withoutInitiator:(work:any)=>work()})
ctx.provide('sessions',{flush:async(session:any)=>{trace.push(['flush',session.id]);return true}})
ctx.provide('sessionPersistence',{stat})
ctx.provide('sessionController',{resolveAgent:async(id:any)=>{trace.push(['activate',id]);throw new Error('unexpected activation')},create:async(request:any)=>{trace.push(['create-session',request]);throw new Error('unexpected creation')}})
ctx.provide('workspaceRegistry',{archivedSessionIds:['archived']})
const backend=new JsonStorageBackend(join(files,'source'));ctx.provide('storage',{backend:{get:()=>backend}})
const facility=new DomainFacility(ctx,{backend:'fixture'});ctx.provide('storageDomain',facility)
ctx.on('schedule/changed',()=>changes.push(true))
const fiber=ctx.plugin(ScheduleService,{});await fiber;const service:any=ctx.schedule
const stable=async()=>{await service.chain;await service.notifications;if(service.runtime.running!==undefined)await service.runtime.running;await Promise.resolve()}
const step=async(label:string,operation:any)=>{
 const start=trace.length,before=changes.length;let answer:any
 try{answer={value:await operation()}}catch(error:any){answer={error:{name:error.name??'Error',code:error.code??null,message:error.message,details:error.details??null}}}
 await stable();rows.push({step:label,...answer,trace:trace.slice(start),changes:changes.length-before});return answer.value
}
try{
 await stable();await step('limits',async()=>service.deliveryLimits())
 const request={title:' First ',prompt:' Prompt ',timing:{kind:'after',after_seconds:3600},target:{kind:'session',sessionId:'target'}}
 const first=await step('create',()=>service.create(request,'actor')),id=first.id
 await step('view',()=>service.view({id}));await step('catalog',()=>service.catalog());await step('list',()=>service.list({}))
 await step('list-inactive',()=>service.list({active:false}));await step('invalid-list',()=>service.remoteList({limit:0}))
 await step('history',()=>service.remoteHistory({id,limit:10}));await step('invalid-history',()=>service.remoteHistory({id,limit:101}))
 await step('missing-view',()=>service.view({id:'missing'}));await step('missing-run',()=>service.run({id:'missing'}))
 await step('pause',()=>service.edit({id,action:'update',patch:{title:'Updated',prompt:'new prompt',active:false},expectedUpdatedAt:first.updatedAt},'editor'))
 await step('conflict',()=>service.remoteEdit({id,action:'update',patch:{title:'stale'},expectedUpdatedAt:first.updatedAt}))
 await step('empty-patch',()=>service.remoteEdit({id,action:'update',patch:{}}))
 await step('retarget',()=>service.edit({id,action:'update',patch:{target:{kind:'new'},timing:{kind:'every',every_seconds:300}}}))
 await step('resume',()=>service.edit({id,action:'update',patch:{active:true,timing:{kind:'after',after_seconds:7200}}}))
 await step('default-create',()=>service.remoteCreate({title:'Default',prompt:'default',timing:{kind:'after',after_seconds:5400}}))
 for(const target of ['missing','inspect-error','child','stored-child','archived'])await step('refuse-'+target,()=>service.remoteCreate({...request,target:{kind:'session',sessionId:target}}))
 const domain=await service.getDomain(),tasks=domain.table('tasks')
 const endedRecord=Object.fromEntries(Object.entries({...first,id:'ended'}).filter(([key])=>['id','kind','title','prompt','afterSeconds','scheduledAt'].includes(key)))
 await tasks.put('ended',scheduleTaskSchema.parse({record:endedRecord,target:{kind:'session',sessionId:'target'},status:'ended'}))
 await step('delete-inactive',()=>service.deleteInactive());await step('delete-inactive-empty',()=>service.deleteInactive())
 const remove=ctx.on('schedule/changed',()=>{throw new Error('observer refused')})
 await step('observer-committed',()=>service.edit({id,action:'update',patch:{title:'Observed'}}));remove()
 await step('delete',()=>service.edit({id,action:'delete'},'actor'));await step('delete-missing',()=>service.remoteEdit({id,action:'delete'}))
 rows.push({step:'final',tasks:[...tasks.entries()].map(([,task]:any)=>task),activationCalls:trace.filter(call=>['activate','create-session'].includes(call[0])).length})
}finally{await fiber.dispose();await facility.closeAll();await backend.close();await ctx.fiber.dispose();globalThis.Date=NativeDate}
console.log(JSON.stringify(normalize(rows)))
