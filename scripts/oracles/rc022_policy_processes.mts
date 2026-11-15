import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{PolicyProcesses}=await load('packages/ptc-runtime/ptc-runtime-node/src/policy-processes.ts'),rows:any[]=[]
for(const action of ['policy','escalated','unpublished','no-store','unscoped','detached','retry','fanout','dispose']){
 const ctx=new Context(),warnings:string[]=[],session={id:'session'},trace:string[]=[],gate=Promise.withResolvers<void>(),tasks:Promise<any>[]=[];let mode='workspace-write',calls=0,failing=['retry','fanout'].includes(action)
 ctx.logger.warn=(error:Error)=>{warnings.push(error.message)}
 if(action!=='no-store'){ctx.provide('sessions');ctx.set('sessions',{get:(id:string)=>id===session.id&&action!=='unpublished'?session:undefined})}
 ctx.provide('sandboxPolicy');ctx.set('sandboxPolicy',{resolve:()=>({mode})})
 const processes=new PolicyProcesses(ctx),release=async()=>{calls++;trace.push('release');await gate.promise;if(failing)throw new Error('cleanup failed');trace.push('released')},policy:any={mode:action==='escalated'?'danger-full-access':'workspace-write',workspaceRoot:process.cwd()}
 if(action!=='unscoped')policy.sessionId='session'
 const detach=processes.register(policy,release);if(action==='detached'){detach();detach()}
 const emit=(id:string,type:string,mode:string)=>ctx.emit('session/event',{id},{type,data:{mode}}),row:any={action}
 try{
  emit('other','sandbox/mode','read-only');emit('session','turn/start','read-only');emit('session','sandbox/mode','workspace-write');row.unrelatedIgnored=calls===0
  let waiting:Promise<any>;if(action==='dispose'){waiting=ctx.fiber.dispose();for(let i=0;i<8&&!calls;i++)await Promise.resolve()}else{mode='read-only';emit('session','sandbox/mode',mode);waiting=processes.wait('session')}
  tasks.push(waiting);row.started=calls;emit('session','sandbox/mode','danger-full-access');row.sharedCleanup=calls===row.started
  if(action==='fanout'){
   const peerGate=Promise.withResolvers<void>();processes.register({...policy},async()=>{trace.push('peer');await peerGate.promise;trace.push('peer-released')});emit('session','sandbox/mode','workspace-write');let settled=false;const both=processes.wait('session').finally(()=>{settled=true});tasks.push(both);gate.resolve();await Promise.allSettled([waiting]);row.waitsForPeer=!settled;peerGate.resolve();waiting=both
  }else gate.resolve()
  try{await waiting;row.result='done'}catch(error:any){row.result=error.message}
  if(['retry','fanout'].includes(action)){failing=false;await processes.wait('session');row.retryCount=calls}
  await processes.wait('other');await processes.wait(undefined);row.trace=[...trace];row.warnings=[...warnings];rows.push(row)
 }finally{gate.resolve();failing=false;await Promise.allSettled(tasks);await ctx.fiber.dispose()}
 row.finalCount=calls
}
process.stdout.write(JSON.stringify(rows))
