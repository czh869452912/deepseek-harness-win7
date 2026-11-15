import {readFileSync} from 'node:fs'
import {getEventListeners} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Access=(await load('packages/api/remote-access/src/index.ts')).default
const cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),ctx=new Context(),owner=await ctx.plugin(Access),access=ctx.remoteAccess,rows:any[]=[],calls:any[]=[]
const GUEST={kind:'guest',guest:'a'},ROOM={kind:'session',id:'a'},OTHER={kind:'session',id:'b'};let state:any={}
function condition(spec:any){return (request:any)=>{
 if(spec[0]==='throw')throw Error('private fixture condition')
 if(spec[0]==='allow')return {kind:'allow'}
 if(spec[0]==='args')return request.args?.text==='allowed'?{kind:'allow'}:{kind:'deny',reason:'requires-args'}
 return {kind:'deny',reason:spec[1]}
}}
try{
 access.registerPolicy('guest',{bindings(principal:any){calls.push(principal);if(state.failure==='bindings')throw Error('private fixture bindings');return state.bindings},explain(){if(state.failure==='explain')throw Error('private fixture explain');return state.explain}})
 for(const c of cases){state={...c,bindings:c.bindings.map((binding:any)=>({...binding,...binding.condition?{condition:condition(binding.condition)}:{}}))};access.invalidate();const before=calls.length,request:any={principal:c.principal??GUEST,action:c.action??'notes/read',resources:c.resources};if('args'in c)request.args=c.args
  const decision=access.decide(request),count=calls.length-before,invocation={peer:{principal:request.principal},request:{namespace:'notes',method:'read'}},scoped=ctx.extend({invocation}).remoteAccess
  rows.push({name:c.name,decision,bindingCalls:count,filtered:[ROOM,OTHER].filter(resource=>scoped.allows(resource)),snapshot:access.snapshotFor(request.principal)})
 }
 state={bindings:[]};access.invalidate();const invocation={peer:{principal:GUEST},request:{namespace:'remoteAccess',method:'follow'}},control=new AbortController(),stream=ctx.extend({invocation}).remoteAccess.follow(control.signal),frames=[(await stream.next()).value]
 state.bindings=[{resource:ROOM,role:{actions:['notes/read','event:notice']}}];access.invalidate({guest:'a',kind:'guest'});frames.push((await stream.next()).value)
 state.bindings=[{resource:OTHER,role:{actions:['notes/write']}}];access.invalidate(GUEST);frames.push((await stream.next()).value,(await stream.next()).value)
 let settled=false;const pending=stream.next().then((value:any)=>{settled=true;return value});await Promise.resolve();access.invalidate({kind:'guest',guest:'other'});await Promise.resolve();const unaffected=!settled;control.abort();await pending
 rows.push({name:'follow',frames,unaffected,followers:access.followers.size,listeners:getEventListeners(control.signal,'abort').length})
 const ownerControl=new AbortController(),ownerStream=access.follow(ownerControl.signal),baseline=(await ownerStream.next()).value,ownerPending=ownerStream.next();await owner.dispose();await ownerPending
 rows.push({name:'owner-unload',baseline,listeners:getEventListeners(ownerControl.signal,'abort').length})
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
