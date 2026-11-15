import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{PtcCalls}=await load('packages/core/tool-executor-ptc/src/ptc-calls.ts'),rows:any[]=[]
for(const action of ['policy','external-abort','waiting-abort','no-policy','failed-call','reset','release-fails','notify-fails','dispose','dispose-reset']){
 const ctx=new Context(),calls=new PtcCalls(ctx),controller=new AbortController(),trace:string[]=[],signals:AbortSignal[]=[],cleanup=Promise.withResolvers<void>(),started=Promise.withResolvers<void>(),released=Promise.withResolvers<void>(),aborted=Promise.withResolvers<void>(),tasks:Promise<any>[]=[],row:any={action};let currentMode='workspace-write'
 const mode=()=>{trace.push('mode:'+currentMode);return action==='no-policy'?undefined:currentMode},body=async(signal:AbortSignal)=>{signals.push(signal);signal.addEventListener('abort',()=>aborted.resolve(),{once:true});trace.push('first');await cleanup.promise;trace.push('cleanup');return 'first'},nextBody=async()=>{trace.push('next');return 'next'},independent=async()=> 'independent',result=async(p:Promise<any>)=>{try{return await p}catch(error:any){return {message:error.message,code:error.code??null}}},release=async()=>{trace.push('release');started.resolve();await released.promise;if(action==='release-fails')throw new Error('release failed')},notify=()=>{trace.push('notice');if(action==='notify-fails')throw new Error('notice failed')}
 const first=calls.run('session',controller.signal,mode,body);tasks.push(first)
 try{
  ctx.emit('session/event',{id:'other'},{type:'sandbox/mode',data:{mode:'read-only'}});ctx.emit('session/event',{id:'session'},{type:'turn/start',data:{turn:1}});ctx.emit('session/event',{id:'session'},{type:'sandbox/mode',data:{mode:'workspace-write'}});row.unrelatedIgnored=!signals[0]!.aborted
  if(['policy','external-abort','waiting-abort','no-policy'].includes(action)){
   currentMode='read-only';if(action==='external-abort')controller.abort(new Error('caller canceled'));else ctx.emit('session/event',{id:'session'},{type:'sandbox/mode',data:{mode:currentMode}});row.aborted=signals[0]!.aborted
   const successor=new AbortController(),second=calls.run('session',successor.signal,mode,nextBody);tasks.push(second);row.blocked=!trace.includes('next');if(action==='waiting-abort')successor.abort(new Error('waiting canceled'));currentMode='danger-full-access';cleanup.resolve();row.first=await result(first);row.next=await result(second)
  }else if(action==='failed-call'){
   row.failed=await result(calls.run('session',new AbortController().signal,mode,async()=>{throw new Error('call failed')}));row.next=await result(calls.run('session',new AbortController().signal,mode,nextBody));row.overlap=!trace.includes('cleanup');cleanup.resolve();await first
  }else if(['reset','release-fails','notify-fails','dispose-reset'].includes(action)){
   const reset=calls.reset('session',release,notify);tasks.push(reset);row.aborted=signals[0]!.aborted;row.sharedReset=calls.reset('session',release)===reset;const second=calls.run('session',new AbortController().signal,mode,nextBody);tasks.push(second);await started.promise;row.blocked=!trace.includes('next');row.independent=await calls.run('other',new AbortController().signal,()=>undefined,independent);released.resolve();row.releaseInsufficient=!trace.includes('next')&&!trace.includes('notice');let disposed:Promise<any>|undefined
   if(action==='dispose-reset'){disposed=ctx.fiber.dispose();tasks.push(disposed);await aborted.promise}
   cleanup.resolve();await first;row.reset=await result(reset)??null;row.next=await result(second)
   if(['release-fails','notify-fails'].includes(action)){row.blockedAfterFailure=await result(calls.run('session',new AbortController().signal,mode,nextBody));await calls.reset('session',async()=>{});row.retry=await result(calls.run('session',new AbortController().signal,mode,nextBody))}
   if(disposed)await disposed
  }else{
   const disposed=ctx.fiber.dispose();tasks.push(disposed);await aborted.promise;row.aborted=signals[0]!.aborted;const second=calls.run('session',new AbortController().signal,mode,nextBody);tasks.push(second);row.blocked=!trace.includes('next');cleanup.resolve();await first;row.next=await result(second);await disposed
  }
  if(['dispose','dispose-reset'].includes(action)){row.late=await result(calls.run('session',new AbortController().signal,mode,nextBody));row.lateReset=await result(calls.reset('session',async()=>{}))}
  row.trace=trace;rows.push(row)
 }finally{cleanup.resolve();released.resolve();await Promise.allSettled(tasks);await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
