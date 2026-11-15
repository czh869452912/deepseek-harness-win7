import {readFileSync} from 'node:fs'
import {setImmediate} from 'node:timers/promises'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{QueryActivity}=await load('packages/sdk/server/src/query-activity.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const testcase of cases){
 const ctx=new Context(),signal=new AbortController(),notifications:any[]=[],closed:any[]=[],idle=Promise.withResolvers<void>();let own=true
 const agent={session:{id:'root'},status:'running',whenIdle:()=>idle.promise};ctx.provide('goals');ctx.goals={get:()=>({phase:'active'})}
 const activity=new QueryActivity(ctx,agent,{notify:(method:string,params:any)=>notifications.push({method,params})},()=>own,signal.signal,()=>closed.push(true))
 try{
  for(const [method,value] of testcase.actions){
   if(method==='accept')activity.accept(value)
   else if(method==='event')ctx.emit('session/event',agent.session,value)
   else if(method==='foreign')ctx.emit('session/event',{id:'other'},value)
   else if(method==='own')own=value
   else if(method==='status'){agent.status=value;ctx.emit('agent/status',{agent,status:value})}
   else if(method==='activation')ctx.emit('goal/activation-changed',value)
   else if(method==='unload')activity.goalUnavailable()
   else if(method==='dispose')ctx.emit('agent/disposed',{agent})
   else if(method==='error')ctx.emit('agent/error',{agent,error:Error('failed')})
   else if(method==='abort')signal.abort(Error('stop'))
   else if(method==='idle'){agent.status='idle';idle.resolve();await setImmediate()}
  }
  rows.push({name:testcase.name,notifications,closed:activity.closed,closeCount:closed.length})
 }finally{activity.close();idle.resolve();await setImmediate();await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
