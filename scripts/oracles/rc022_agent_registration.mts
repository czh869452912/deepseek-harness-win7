import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Registry}=await load('packages/session/session-projection/src/index.ts'),{default:Agents}=await load('packages/core/agent/src/index.ts'),rows:any[]=[]
for(const action of ['serial','sync-reject','async-reject','detach-await','split-stale','payload','owner-order','reentrant-announce','effect-repeat','effect-awaited','effect-owner-join']){
 const ctx=new Context(),trace:string[]=[],row:any={action},jobs:any[]=[];let release:any,start:any;const gate=new Promise(resolve=>{release=resolve}),entered=new Promise(resolve=>{start=resolve})
 try{
  await ctx.plugin(Registry);await ctx.plugin(Agents);const agents=ctx.agents,agent:any={id:'agent',session:{id:'agent'},ctx};ctx.on('agent/disposed',()=>{trace.push('disposed')})
  if(action.startsWith('effect-')){
   let owner:any;const ownerFiber=await ctx.plugin((scope:any)=>{owner=scope}),disposer=owner.effect(()=>async()=>{trace.push('cleanup:start');start();await gate;trace.push('cleanup:end')},'test pending effect'),selected=action==='effect-awaited'?await disposer:disposer;row.different=selected!==disposer;const first=selected();jobs.push(first);await entered;row.repeat=selected()===undefined;row.wrapperRepeat=disposer()===undefined;if(action==='effect-owner-join'){let done=false;const closing=ownerFiber.dispose().then(()=>{done=true});jobs.push(closing);await Promise.resolve();row.waiting=!done}release();await Promise.all(jobs);row.trace=[...trace];row.after=selected()===undefined
  }else if(['serial','detach-await'].includes(action)){
   let detach:any;ctx.on('agent/created',async()=>{trace.push('first:start');if(action==='detach-await'){detach();trace.push(agents.get('agent')===agent?'live':'missing')}start();await gate;trace.push('first:end')});ctx.on('agent/created',()=>{trace.push('second')});let registration:any;if(action==='detach-await'){detach=agents.enter(agent);registration=agents.announce(agent,'resume')}else registration=agents.register(agent)
   const job=Promise.resolve(registration).then(()=>{trace.push('ready')});jobs.push(job);await entered;row.waiting=[...trace];try{await agents.announce(agent,'startup')}catch(error:any){row.reentrant=error.message}release();await job;row.settled=[...trace];row.live=agents.get('agent')===agent;if(action==='serial'){await registration();row.disposed=[...trace];row.repeat=registration()===undefined}
  }else if(['sync-reject','async-reject'].includes(action)){
   const primary=new Error('creation rejected'),fail=()=>{trace.push('rejected');throw primary};ctx.on('agent/created',action==='sync-reject'?fail:async()=>{trace.push('first:start');await Promise.resolve();fail()});ctx.on('agent/created',()=>{trace.push('unreachable')});try{await agents.register(agent)}catch(error){row.same=error===primary}row.trace=[...trace];row.removed=agents.get('agent')===undefined
  }else if(action==='split-stale'){
   const detach=agents.enter(agent);row.unannounced=[...trace];await agents.announce(agent,'startup');detach();detach();const replacement:any={id:'agent',session:{id:'agent'},ctx},remove=agents.enter(replacement);detach();row.replacement=agents.get('agent')===replacement;try{await agents.announce(agent,'startup')}catch(error:any){row.stale=error.message}remove();row.trace=[...trace]
  }else if(action==='payload'){
   const signal=new AbortController().signal;ctx.on('agent/created',(payload:any)=>{row.subject=payload.agent===agent;row.source=payload.source;row.signal=payload.signal===signal;row.keys=Object.keys(payload).sort()});const detach=agents.enter(agent);await agents.announce(agent,'compaction',signal);detach()
  }else if(action==='owner-order'){
   let owner:any;const ownerFiber=await ctx.plugin(Object.assign((scope:any)=>{owner=scope},{inject:['agents']})),registration=owner.agents.register(agent);await registration;owner.effect(function*(){yield registration;yield async()=>{trace.push('drain:start');start();await gate;trace.push('drain:end')}},'ordered agent lifetime');const job=ownerFiber.dispose();jobs.push(job);await entered;row.waiting=[...trace];row.liveBefore=agents.get('agent')===agent;release();await job;row.trace=[...trace];row.removed=agents.get('agent')===undefined
  }else{ctx.on('agent/created',async()=>{try{await agents.announce(agent,'startup')}catch(error:any){row.reentrant=error.message}});const registration=agents.register(agent);await registration;row.live=agents.get('agent')===agent;await registration()}
  rows.push(row)
 }finally{release();await Promise.allSettled(jobs);await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
