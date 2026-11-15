import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),fixture=await setup(join(workspace,'source')),ctx=fixture.ctx,rows:any[]=[],tasks:Promise<any>[]=[],promotions:string[]=[],opened:any[]=[],streams:any[]=[]
const {HistoryController}=await load('packages/api/session-controller/src/history/controller.ts'),{WebController}=await load('packages/api/session-controller/src/web/controller.ts'),{ApiSessionAgentController}=await load('packages/api/session-controller/src/agent.ts')
const {appendPluginRecord}=await load('packages/core/session/src/index.ts')
try{
 await ctx.plugin((await load('packages/typert/registry/src/index.ts')).default)
 ctx.provide('agentDefaultModel',{currentSelection:()=>({provider:'script',model:'model'})})
 const agents=new ApiSessionAgentController(ctx);agents.initialize();const history=new HistoryController(ctx),web=new WebController(ctx,history,(observation:any)=>{
  promotions.push(observation.header.id);tasks.push((async()=>{try{const found=await agents.resolveObservedAgent(observation);if('error'in found)throw found.error}finally{observation[Symbol.dispose]()}})())
 })
 const handle=await ctx.agents.create({sessionId:'follow',meta:{cwd:'C:/follow'},agentOptions:{provider:'script',model:'model'}}),session=handle.agent.session,emit=(frame:any)=>ctx.emit('agent/assistant-stream',{agent:handle.agent,frame})
 appendPluginRecord(session,'plugin:fixture/tick',{value:0});emit({type:'start',attemptId:'attempt',revision:1,turn:1,step:1})
 const query=ctx.sessionQuery.observeSession.bind(ctx.sessionQuery);let race=true
 ctx.sessionQuery.observeSession=async(id:any,options:any)=>{
  const observed=await query(id,options),receipt={released:false};opened.push(receipt)
  const value={...observed,retain:()=>observed.retain(),[Symbol.dispose]:()=>{receipt.released=true;observed[Symbol.dispose]()}}
  // Preserve the borrowed event getter rather than materializing it during wrapper construction.
  Object.defineProperty(value,'events',{get:()=>observed.events})
  if(race){race=false;appendPluginRecord(session,'plugin:fixture/tick',{value:1});emit({type:'chunk',attemptId:'attempt',revision:2,index:0,time:4,chunk:{type:'text-delta',index:0,text:'partial'}})}
  return value
 }
 const address={kind:'session',sessionId:'follow'},live=web.follow({address,assistantStream:true,activate:true},fixture.signal)[Symbol.asyncIterator]();streams.push(live)
 const opening=(await live.next()).value;rows.push({name:'live-opening',value:opening,promotions:[...promotions],leaseReleased:opened.at(-1).released})
 emit({type:'end',attemptId:'attempt',revision:3,index:1,outcome:{kind:'abandoned'}});appendPluginRecord(session,'plugin:fixture/tick',{value:2})
 rows.push({name:'uncovered-mixed',values:[(await live.next()).value,(await live.next()).value,(await live.next()).value]});await live.return?.();await handle.dispose()
 const passive=web.follow({address,assistantStream:true},fixture.signal)[Symbol.asyncIterator]();streams.push(passive)
 rows.push({name:'cold-default-passive',value:(await passive.next()).value,promotions:[...promotions],agentAbsent:ctx.agents.get('follow')===undefined,leaseReleased:opened.at(-1).released});await passive.return?.()
 const active=web.follow({address,activate:true},fixture.signal)[Symbol.asyncIterator]();streams.push(active);const value=(await active.next()).value
 rows.push({name:'promotion-before-opening',cursor:value.cursor,promotions:[...promotions],leaseReleased:opened.at(-1).released});await active.return?.();await Promise.all(tasks)
 rows.push({name:'promotion-outlives-consumer',attached:ctx.agents.get('follow')!==undefined})
 const missing=web.follow({address:{kind:'subagent',parentSessionId:'parent',childSessionId:'missing',mode:'unknown'}},fixture.signal)[Symbol.asyncIterator]();streams.push(missing)
 try{await missing.next()}catch(error:any){rows.push({name:'missing-subagent',code:error.code,details:error.details})}
 const abort=new AbortController();abort.abort();const cancelled=web.follow({address},abort.signal)[Symbol.asyncIterator]();streams.push(cancelled)
 try{await cancelled.next()}catch(error:any){rows.push({name:'already-cancelled',nameOfError:error.name})}
}finally{for(const stream of streams)await stream.return?.();await Promise.allSettled(tasks);await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows,(key,value)=>key==='createdAt'?0:value&&typeof value==='object'&&'type'in value&&'seq'in value&&'time'in value?{...value,time:0}:value))
