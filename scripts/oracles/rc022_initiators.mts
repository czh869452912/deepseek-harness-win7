import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context,FiberState}=await load('vendor/cordis/src/index.ts'),{default:Registry}=await load('packages/session/session-projection/src/index.ts'),{default:Agents}=await load('packages/core/agent/src/index.ts')
const mount=async()=>{const ctx=new Context();await ctx.plugin(Registry);const fiber=await ctx.plugin(Agents);return {ctx,fiber,service:ctx.agents}},read=(service:any)=>{try{return {value:service.currentInitiator()?.id??null}}catch(error:any){return {error:error.message}}},rows:any[]=[]
for(const action of ['sync','nested','overlap','drain','self-dispose','ancestor-dispose','async-unrelated','cross-registry','promise-identity','plain-awaitable','throws']){
 const {ctx,fiber,service}=await mount(),row:any={action},a={id:'a'},b={id:'b'},releases:any[]=[],jobs:any[]=[];let otherCtx:any
 try{
  if(action==='sync'){const value={};row.same=service.withInitiator(a,()=>{row.inside=read(service);return value})===value;row.outside=read(service)}
  else if(action==='nested'){const trace:any[]=[];service.withInitiator(a,()=>{trace.push(read(service));service.withInitiator(b,()=>trace.push(read(service)));trace.push(read(service));service.withoutInitiator(()=>trace.push(read(service)));trace.push(read(service))});row.trace=trace;row.outside=read(service)}
  else if(['overlap','drain','async-unrelated'].includes(action)){
   let release:any;const gate=new Promise(resolve=>{release=resolve}),trace:any[]=[],run=async()=>{trace.push(read(service));await gate;trace.push(read(service))};releases.push(release)
   if(action==='overlap'){jobs.push(service.withInitiator(a,run),service.withInitiator(b,run));row.outside=read(service);release();await Promise.all(jobs);row.trace=trace}
   else if(action==='drain'){const job=service.withInitiator(a,run);jobs.push(job);let done=false;const closing=fiber.dispose().then(()=>{done=true});row.state=service.initiatorState;row.hidden=ctx.get('agents')===undefined;row.waiting=!done;for(const [key,operation] of [['with',()=>service.withInitiator(b,()=>1)],['without',()=>service.withoutInitiator(()=>1)]] as const){try{operation()}catch(error:any){row[key]=error.message}}release();await job;await closing;row.trace=trace;row.after=read(service)}
   else{const sibling=service.withInitiator(b,run);jobs.push(sibling);let closedResolve:any;const closed=new Promise(resolve=>{closedResolve=resolve});ctx.on('internal/status',(owner:any)=>{if(owner.state===FiberState.UNLOADING)closedResolve()});let done=false;const own=service.withInitiator(a,async()=>{await Promise.resolve();await ctx.fiber.dispose()});jobs.push(own);void own.then(()=>{done=true});await closed;row.waiting=!done;row.state=service.initiatorState;release();await Promise.all(jobs);row.trace=trace;row.after=read(service)}
  }else if(['self-dispose','ancestor-dispose'].includes(action)){let returned:any;const shutdown=()=>{returned=(action==='self-dispose'?fiber:ctx.fiber).dispose();return returned},result=action==='self-dispose'?service.withInitiator(a,shutdown):service.withInitiator(a,()=>service.withInitiator(b,shutdown));jobs.push(result);row.same=result===returned;await result;row.after=read(service)}
  else if(action==='cross-registry'){const other=await mount();otherCtx=other.ctx;row.other=service.withInitiator(a,()=>read(other.service));row.own=service.withInitiator(a,()=>read(service));await other.fiber.dispose()}
  else if(action==='promise-identity'){let release:any;const value=new Promise(resolve=>{release=resolve});jobs.push(value);row.same=service.withInitiator(a,()=>value)===value;let done=false;const closing=fiber.dispose().then(()=>{done=true});row.waiting=!done;release('done');await value;await closing;row.after=read(service)}
  else if(action==='plain-awaitable'){const value={then:()=>{throw new Error('thenable must not be assimilated')}};row.same=service.withInitiator(a,()=>value)===value;await fiber.dispose();row.after=read(service)}
  else{const primary=new Error('sync failure');try{service.withInitiator(a,()=>{throw primary})}catch(error){row.syncSame=error===primary}const job=service.withInitiator(b,async()=>{await Promise.resolve();throw primary});jobs.push(job);try{await job}catch(error){row.asyncSame=error===primary}row.outside=read(service)}
  rows.push(row)
 }finally{for(const release of releases)release();await Promise.allSettled(jobs);if(otherCtx)await otherCtx.fiber.dispose();await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
