import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Registry}=await load('packages/session/session-projection/src/index.ts'),{default:Agents}=await load('packages/core/agent/src/index.ts'),{default:Types}=await load('packages/typert/registry/src/index.ts')
const rows:any[]=[]
for(const action of ['states','running-to-idle','idle-to-running','stop','stop-throws','dispose','types-before','types-after']){
 const ctx=new Context(),row:any={action},jobs:any[]=[],releases:any[]=[]
 try{
  await ctx.plugin(Registry);if(action==='types-before')await ctx.plugin(Types)
  const fiber=await ctx.plugin(Agents),agents=ctx.agents,calls:any[]=[],cancel=(...args:any[])=>{calls.push([args[0],args[1]??null])},agent:any={id:'busy',session:{id:'busy'},ctx,status:'running',cancel},detach=agents.enter(agent),ask=(sessionId='busy')=>ctx.waterfall('workspace/session-activity',{sessionId},async()=>[]),stop=(sessionId='busy')=>ctx.parallel('workspace/session-stop',{sessionId})
  if(action==='states'){ctx.on('workspace/session-activity',async(_req:any,next:any)=>[...(await next()),{kind:'probe'}]);row.running=await ask();agent.status='idle';row.idle=await ask();row.unknown=await ask('unknown');detach();row.detached=await ask()}
  else if(['running-to-idle','idle-to-running'].includes(action)){
   let start:any,release:any;const started=new Promise(resolve=>{start=resolve}),gate=new Promise(resolve=>{release=resolve}),rest=[{kind:'probe'}];releases.push(release)
   ctx.on('workspace/session-activity',async()=>{start();await gate;return rest});agent.status=action==='running-to-idle'?'running':'idle';const task=ask();jobs.push(task);await started;agent.status=agent.status==='running'?'idle':'running';release();const result=await task;row.result=result;row.same=result===rest
  }else if(action==='stop'){let settled=false;const pending=new Promise(()=>{});agent.cancel=(...args:any[])=>{cancel(...args);return pending};void pending.then(()=>{settled=true});await stop();row.calls=[...calls];row.notAwaited=!settled;agent.status='idle';await stop();await stop('unknown');row.afterIdle=calls.length}
  else if(action==='stop-throws'){const primary=new Error('cancel failed');agent.cancel=()=>{throw primary};try{await stop()}catch(error:any){row.same=error===primary;row.contained=error.errors[0]===primary;row.count=error.errors.length}}
  else if(action==='dispose'){row.before=await ask();await fiber.dispose();row.after=await ask();await stop();row.calls=calls}
  else{if(action==='types-after')await ctx.plugin(Types);const types=ctx.typert,lookup=types.lookups.get('agent'),adapter=types.contexts.getHost('agent');row.lookup=Object.fromEntries(['parameter','wire','resource','hostTypeSymbol','wireTypeSymbol'].map(key=>[key,lookup[key]]));row.context=Object.fromEntries(['wire','resource','wireTypeSymbol'].map(key=>[key,adapter[key]]));row.resolved=lookup.resolve('busy')===agent;row.scoped=adapter.resolve('busy')===ctx;row.unknown=lookup.resolve('unknown')===undefined;await fiber.dispose();row.withdrawn=types.lookups.get('agent')===undefined&&types.contexts.getHost('agent')===undefined}
  rows.push(row)
 }finally{for(const release of releases)release();await Promise.allSettled(jobs);await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
