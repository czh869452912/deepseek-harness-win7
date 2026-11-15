import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const source=process.argv[2]!,load=(path:string)=>import(pathToFileURL(resolve(source,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts')
const {default:SessionStore}=await load('packages/core/session/src/index.ts')
const results=[]
for(const action of ['unload','dispose','duplicate','unrelated']){
 const ctx=new Context();let dispose:any
 const definition={type:'test/project',project:(event:any,context:any)=>{
  const seq=event.data.seq,original=context.messages.get(seq)??context.events[seq-context.baseSeq].data
  return new Map([[seq,{...original,content:[{type:'text',text:event.data.text}]}]])
 }}
 try{
  await ctx.plugin(SessionStore)
  const fiber=await ctx.plugin({inject:['sessions'],apply(owner:any){dispose=owner.sessions.registerMessageProjection(definition)}})
  const store=ctx.sessions,borrowed=store.messageProjections,result:any={name:action,registered:borrowed.map((item:any)=>item.type)}
  if(action==='duplicate'){try{store.registerMessageProjection({...definition})}catch(error:any){result.duplicate=error.message}}
  const input=(session:any)=>session.append('user/message',{id:'user',role:'user',source:{kind:'user'},content:[{type:'text',text:'original'}]},{surfaceOp:'append'})
  const live=store.create('live');input(live);live.append('test/project',{seq:0,text:'changed'})
  const pending=store.create('pending');input(pending);pending.append('test/project',{seq:0,text:'pending'})
  const before=live.deriveMessages(),child=store.fork(live)
  const restored=store.prepare('restored',{seed:live.snapshotEvents(),meta:{...live.header,id:'restored'},inheritedEventCount:live.inheritedEventCount,eventState:'shared-frozen'})
  ctx.effect(()=>store.enter(restored));store.announce(restored)
  result.before=[live,child,restored].map(session=>session.deriveMessages()[0].content)
  if(action==='dispose')await dispose()
  else if(action==='unrelated')await store.registerMessageProjection({type:'test/unused',project:definition.project})()
  else await fiber.dispose()
  Object.assign(result,{remaining:borrowed.map((item:any)=>item.type),sameBorrowed:store.messageProjections===borrowed,snapshotRetained:before[0].content[0].text==='changed',outcomes:[]})
  for(const session of [live,pending,child,restored]){
   const outcomes=[]
   for(const callback of [()=>session.deriveMessages(),()=>session.deriveEventMessage(session.eventAt(0)),()=>session.surface.replaceGeneration,()=>session.surface.contentGeneration,()=>session.append('turn/start',{turn:1})]){
    try{callback();outcomes.push('value')}catch(error:any){outcomes.push(error.message)}
   }
   result.outcomes.push(outcomes)
  }
  results.push(result)
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(results))
