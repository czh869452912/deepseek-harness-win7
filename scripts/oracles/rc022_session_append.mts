import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Store}=await load('packages/core/session/src/index.ts')
const rows=JSON.parse(readFileSync(process.argv[3]!,'utf8')),results=[]
for(const row of rows){
 const ctx=new Context(),name=row.name,result:any={name,observed:[],extra:[],reentry:[]}
 try{
  await ctx.plugin(Store);const store=ctx.sessions
  store.registerMessageProjection({type:'test/project',project:(event:any,context:any)=>{
   if(event.data.text==='reject')throw new Error('rejected decision')
   const seq=event.data.seq,original=context.events[seq-context.baseSeq].data
   return new Map([[seq,{...original,content:[{type:'text',text:event.data.text}]}]])
  }})
  const session=store.prepare('batch'),detach=store.enter(session);store.announce(session)
  ctx.on('session/event',(current:any,event:any)=>{
   result.observed.push({seq:event.seq,length:current.seq,nodes:[...current.surface.nodes],messages:current.deriveMessages().map((value:any)=>value.content),member:current.currentBatchPublication===event,live:store.get(current.id)===current})
   if(name==='reentrant'){try{current.append('turn/end',{})}catch(error:any){result.reentry.push(error.message)}}
   if(name==='detach')detach()
   if(name==='listener-change'&&event.seq===0)ctx.on('session/event',(current:any,member:any)=>result.extra.push(member.seq))
  })
  ctx.on('internal/dispatch',(mode:any,event:any,args:any[])=>{if(name==='dispatch-veto'&&event==='session/event'&&args[1].seq===1)throw new Error('veto final event')})
  try{result.returned=session.append(row.inputs.map((item:any)=>item===null?undefined:item)).map((event:any)=>event.seq)}catch(error:any){result.error=error.message}
  Object.assign(result,{seq:session.seq,nodes:[...session.surface.nodes],messages:session.deriveMessages().map((value:any)=>value.content),publicationCleared:session.currentBatchPublication===undefined,live:store.get(session.id)===session})
  if(name==='detach'){try{session.append([])}catch(error:any){result.afterDetach=error.message}}
  if(name==='listener-change')session.append('turn/end',{})
  results.push(result)
 }finally{await ctx.fiber.dispose()}
}
for(const action of ['normal','failed','detach-created']){
 const ctx=new Context(),result:any={name:'membership-'+action,stages:[]}
 try{
  await ctx.plugin(Store);const store=ctx.sessions,session=store.prepare('membership')
  const attempt=()=>{try{session.append([]);return 'value'}catch(error:any){return error.message}}
  result.stages.push(attempt());const detach=store.enter(session);result.stages.push(attempt())
  const stop=ctx.on('session/created',()=>{result.stages.push(attempt());if(action==='failed')throw new Error('creation observer failed');if(action==='detach-created')detach()})
  try{store.announce(session)}catch(error:any){result.announcement=error.message}
  result.stages.push(attempt())
  if(action==='failed'){try{store.announce(session)}catch(error:any){result.reannounce=error.message}}
  detach();result.stages.push(attempt());stop()
  const replacement=store.create('membership');Object.assign(result,{replacement:replacement.seq,old:attempt()});results.push(result)
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(results))
