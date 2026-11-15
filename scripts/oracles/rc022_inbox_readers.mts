import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Store,Session}=await load('packages/core/session/src/index.ts'),{default:Registry}=await load('packages/session/session-projection/src/index.ts'),{ReactLoopInbox,inboxProjectionDefinition}=await load('packages/core/agent-loop/src/inbox.ts')
const message=(id:string)=>({id,role:'user',content:[{type:'text',text:id}],source:{kind:'user'}}),rows=[]
for(const action of ['live','detached','replacement','reader-failure','lazy','independent']){
 const ctx=new Context();try{
  await ctx.plugin(Store);await ctx.plugin(Registry);const registry=ctx.sessionProjections,handle=await registry.register(inboxProjectionDefinition),session=action==='detached'?Session.create('inbox'):ctx.sessions.create('inbox'),row:any={action},notifications:any[]=[];let reads=0;const primary=new Error('reader failed')
  const inbox=new ReactLoopInbox(()=>{reads++;if(action==='reader-failure')throw primary;return handle.stateOf(session)},session,{emit:(name:any,payload:any)=>notifications.push({name,payload})});row.constructorReads=reads
  if(action==='reader-failure'){
   const failures=[];for(const operation of [()=>inbox.nextTurn,()=>inbox.hasPending,()=>inbox.append('next-turn',message('a'))]){try{operation()}catch(error){failures.push(error===primary)}}row.failures=failures;row.eventCount=session.snapshotEvents().length;row.notifications=notifications;rows.push(row);continue
  }
  if(action==='lazy'){await handle.dispose();row.unread=registry.checkpoint(session);row.read=inbox.hasPending;row.after=registry.checkpoint(session);rows.push(row);continue}
  inbox.append('next-turn',message('turn'));inbox.append('next-step',message('step'));const captured=inbox.nextStep;inbox.prepend('next-turn',message('front'));row.replaced=inbox.replace('turn',message('new'));row.missing=inbox.remove('missing');row.claimed=inbox.claim('next-turn',5);row.captured=captured;row.before={turn:inbox.nextTurn,step:inbox.nextStep};await handle.dispose();row.released=registry.checkpoint(session)
  if(action==='replacement'){const replacement=await registry.register(inboxProjectionDefinition);row.replacement=replacement.stateOf(session)}
  if(action==='independent'){const other=ctx.sessions.create('other'),second=new ReactLoopInbox(handle.readerFor(other),other,{emit:()=>{}});second.append('next-turn',message('other'));row.other=second.nextTurn}
  inbox.append('next-step',message('retained'));row.retained={turn:inbox.nextTurn,step:inbox.nextStep};inbox.clear();row.cleared=inbox.hasPending;row.notifications=notifications;row.events=session.snapshotEvents().map(({seq,type,data}:any)=>({seq,type,data}));rows.push(row)
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
