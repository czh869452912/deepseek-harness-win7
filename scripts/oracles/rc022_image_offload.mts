import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const Store=(await load('packages/core/session/src/index.ts')).default
const plugin=await load('packages/compaction/compaction-image-offload/src/index.ts')
const {offloadOldestImages}=await load('packages/compaction/compaction-image-offload/src/image-offload.ts')
const {LlmError}=await load('packages/llm/llm/src/index.ts')
const {normalizeLlmFailure}=await load('packages/llm/llm/src/adapter-failure.ts')
const cases=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows=[]
const image=(name:string)=>({type:'image',attachment:{attachmentId:'sha256:'+'a'.repeat(64),name,mediaType:'image/png',bytes:1,width:1,height:1}})
const message=(id:string,content:any[])=>({id,role:'user',source:{kind:'human'},content})
for(const test of cases){
 if(test.kind==='normalize'){
  rows.push({case:test,result:normalizeLlmFailure(new LlmError('budget','IMAGE_OFFLOAD_REQUIRED',{status:413,offloadImages:test.value}))})
  continue
 }
 const ctx=new Context();ctx.provide('agents',{});await ctx.plugin(Store)
 const mounted=await ctx.plugin(plugin),session=ctx.sessions.prepare('repair'),detach=ctx.sessions.enter(session)
 ctx.sessions.announce(session)
 try{
  const first=session.append('user/message',message('first',[image('first'),image('second')]),{surfaceOp:'append'})
  const last=session.append('user/message',message('last',[image('third')]),{surfaceOp:'append'})
  const selected=[first.seq,last.seq],controller=new AbortController();let result
  if(test.kind==='selection'){
   if(test.reverse)selected.reverse()
   const initial=offloadOldestImages(session,selected,test.count),remainder=offloadOldestImages(session,selected,9)
   result={first:initial,remainder,exhausted:offloadOldestImages(session,selected,1)}
  }else{
   const mode=test.mode;if(mode==='aborted')controller.abort(new Error('controlled abort'))
   const failure={message:'budget',code:mode==='other'?'OTHER':'IMAGE_OFFLOAD_REQUIRED',...mode==='missing'?{}:{offloadImages:1}}
   try{
    if(test.kind==='agent')result=await ctx.waterfall('agent/request-error',{agent:{session},failure,signal:controller.signal},()=> 'next')
    else{
     const error=mode==='foreign'?Object.assign(new Error('budget'),{code:failure.code,failure}):LlmError.fromFailure(failure)
     result=await ctx.waterfall('compaction/summary-error',{session,sourceEventSeqs:[last.seq],error,signal:controller.signal},()=> 'next')
    }
   }catch(error:any){result={error:error.message,same:error===controller.signal.reason}}
  }
  const decisions=session.snapshotEvents().filter((event:any)=>event.type==='image/offload').map((event:any)=>event.data)
  const names=session.deriveMessages().flatMap((value:any)=>value.content.filter((block:any)=>block.type==='image'&&block.offloaded===true).map((block:any)=>block.attachment.name))
  const nodes=[...session.surface.nodes]
  await mounted.dispose()
  const after=await ctx.waterfall('agent/request-error',{},()=> 'unloaded')
  rows.push({case:test,result,decisions,names,nodes,after,projections:ctx.sessions.messageProjections.length})
 }finally{detach();await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
