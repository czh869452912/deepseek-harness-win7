import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Probe}=await load('packages/client/ui-plugin-manager/src/index.ts'),rows:any[]=[]
const originalFetch=globalThis.fetch,originalNow=Date.now
try{for(const name of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const ctx=new Context(),requests:any[]=[],calls:any[]=[],releases:any[]=[];let now=1000
 Date.now=()=>now
 const owner=await ctx.plugin(Probe,{registryProbeEnabled:name!=='disabled',registryProbeTimeoutMs:name==='timeout'?10:5000,registryProbeCacheTtlMs:name==='zero-ttl'?0:50}),service=ctx.pluginRegistryProbe
 globalThis.fetch=((endpoint:string,{signal,redirect}:any)=>{
  const deferred=Promise.withResolvers<any>();requests.push({...deferred,signal});calls.push({endpoint,redirect})
  const abort=()=>deferred.reject(signal.reason);signal.addEventListener('abort',abort,{once:true})
  return deferred.promise.finally(()=>signal.removeEventListener('abort',abort))
 }) as typeof fetch
 const ticks=async()=>{for(let i=0;i<12;i++)await Promise.resolve()}
 function answer(index:number,status=200){requests[index].resolve({ok:status>=200&&status<300,status,body:{cancel:async()=>{
  calls.push({cancel:index});if(name==='cleanup-wait'){const gate=Promise.withResolvers<void>();releases.push(gate);await gate.promise}
  if(name==='cleanup-reject')throw Error('body already aborted')
 }}})}
 const keepalive=name==='timeout'?setTimeout(()=>{},100):undefined
 const first=service.fastest(),shared=service.fastest();let settled=false;shared.then(()=>settled=true);await ticks()
 try{
  if(name==='dispose')await owner.dispose()
  else if(name==='disabled'||name==='timeout'){}
  else if(name==='offline'){requests[0].reject(Error('offline'));answer(1,500)}
  else if(name==='http-failure'){answer(0,503);answer(1,204)}
  else answer(name==='mirror'||name==='cleanup-reject'?1:0)
  await ticks();const blocked=name==='cleanup-wait'?!settled:null
  for(const gate of releases)gate.resolve()
  const value=await shared;if(await first!==value)throw Error('shared result mismatch')
  let cached=null,refreshed=null
  if(['official','mirror','offline'].includes(name)){
   cached=await service.fastest()
   if(name!=='offline'){now=1050;const fresh=service.fastest();await ticks();answer(2,204);refreshed=await fresh}
  }
  if(name==='zero-ttl'){const fresh=service.fastest();await ticks();answer(3,204);refreshed=await fresh}
  await owner.dispose();let rejected=false;try{await service.fastest()}catch{rejected=true}
  rows.push({name,value,cached,refreshed,calls,signals:requests.map(r=>r.signal.aborted),listeners:requests.map(()=>0),blocked,rejected,withdrawn:ctx.get('pluginRegistryProbe')===undefined})
 }finally{if(keepalive)clearTimeout(keepalive);for(const gate of releases)gate.resolve();await ctx.fiber.dispose()}
}}finally{globalThis.fetch=originalFetch;Date.now=originalNow}
console.log(JSON.stringify(rows))
