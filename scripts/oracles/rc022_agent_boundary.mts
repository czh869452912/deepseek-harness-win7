import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Store,Session}=await load('packages/core/session/src/index.ts'),{default:Registry}=await load('packages/session/session-projection/src/index.ts'),{default:Agents}=await load('packages/core/agent/src/index.ts')
const rows=[]
for(const action of ['detached','live','replacement','deferred']){
 const ctx=new Context();try{
  await ctx.plugin(Store);await ctx.plugin(Registry);const projections=ctx.sessionProjections,row:any={action}
  if(action==='deferred'){
   let enter:any,release:any;const entered=new Promise(resolve=>{enter=resolve}),gate=new Promise(resolve=>{release=resolve}),original=projections.register.bind(projections)
   projections.register=async(definition:any)=>{enter();await gate;return original(definition)};const fiber=ctx.plugin(Agents);await entered;row.waiting=fiber.state;release();await fiber;row.ready=fiber.state;rows.push(row);continue
  }
  const fiber=await ctx.plugin(Agents),agents=ctx.agents,session=action==='detached'?Session.create('boundary'):ctx.sessions.create('boundary');row.initial=agents.turnBoundaryOf(session);session.append('turn/start',{turn:3});session.append('step/start',{turn:3,step:1});row.open=agents.turnBoundaryOf(session);session.append('step/end',{turn:3,step:1});session.append('turn/end',{turn:3});row.closed=agents.turnBoundaryOf(session);row.checkpoint=projections.checkpoint(session);await fiber.dispose();session.append('turn/start',{turn:4});row.released=projections.checkpoint(session);row.unread=projections.checkpoint(Session.create('unread'));row.retained=agents.turnBoundaryOf(session)
  if(action==='replacement'){await ctx.plugin(Agents);row.replacement=ctx.agents.turnBoundaryOf(session);row.newCheckpoint=projections.checkpoint(session)}rows.push(row)
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
