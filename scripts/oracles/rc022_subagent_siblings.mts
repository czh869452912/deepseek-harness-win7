import {resolve,join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href),workspace=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source')
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Loop}=await load('packages/core/agent-loop/src/index.ts'),Backend=await load('packages/session/session-persistence-jsonl/src/index.ts'),{default:Subagents}=await load('packages/subagent/subagent/src/index.ts'),Spawn=await load('packages/subagent/subagent-spawn-in-process/src/index.ts')
const {TestSessionQuery}=await load('packages/subagent/subagent/tests/test-session-query.ts'),{MockAdapter}=await load('packages/core/agent-loop/tests/mock-adapter.ts'),plugins:any[]=[],rows:any[]=[]
for(const path of ['packages/llm/llm/src/index.ts','packages/core/session/src/index.ts','packages/session/session-projection/src/index.ts','packages/core/system-prompt/src/index.ts','packages/core/tools/src/index.ts','packages/core/tool-executor-native/src/index.ts','packages/core/agent/src/index.ts']){const module=await load(path);plugins.push(module.default??module)}
class Hanging extends MockAdapter{
 override async *stream(options:any){
  yield {type:'block-start',index:0,blockType:'text'} as const
  yield {type:'text-delta',index:0,text:'partial'} as const
  await new Promise((_resolve,reject)=>{if(options.signal.aborted)reject(Error('aborted'));else options.signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true})})
 }
}
for(const action of ['live','cold-creator','provider-removed','sender-stale','root-replaced','unreadable','capacity','parent-direct','outside']){
 const ctx=new Context(),row:any={action},received:any[]=[];for(const plugin of plugins)await ctx.plugin(plugin)
 await ctx.plugin(Backend,{root:join(workspace,action),compression:'none'});await ctx.plugin(Loop,{agents:[]});ctx.llm.registerAdapter(['script'],new Hanging([]));await ctx.plugin(TestSessionQuery)
 ctx.provide('workingDirectory');ctx.workingDirectory={ensure:async()=> 'C:/rc022-work',set:async(_agent:any,path:string)=>path}
 await ctx.plugin(Subagents,{maxActiveSubagents:3});const providerOwner=await ctx.plugin(Spawn),service=ctx.subagents,manager=service['manager'],query=ctx.sessionQuery,signal=new AbortController().signal
 const parent=(await ctx.agents.create({sessionId:'root',agentOptions:{provider:'script',model:'model'}})).agent
 ctx.on('agent/pre-step',async({agent}:any,next:any)=>agent===parent?{kind:'reject'}:next())
 const start=async(creator:any,id:string)=>{const receipt=await service.startActivation({provider:'spawn',parent:creator,childId:id,name:id,label:'Task',prompt:[{type:'text',text:'TASK:'+id}],signal,delivery:'caller'});while(ctx.agents.get(id).status!=='running')await new Promise(r=>setTimeout(r,1));return [receipt,ctx.agents.get(id)]}
 const [a,sender]=await start(parent,'a'),[b,branch]=await start(parent,'b'),[leaf,target]=await start(branch,'leaf')
 const originalGet=ctx.agents.get,originalObserve=query.observeSession;let stale=false
 ctx.on('agent/inbox/inserted',({agent,message}:any)=>{if(message.source.kind==='agent-message')received.push({target:agent.id,sender:message.source.senderSessionId,text:message.content.filter((b:any)=>b.type==='text').map((b:any)=>b.text).join('')})})
 const send=(who:any,id:string,text:string)=>service.sendMessage(who,id,[{type:'text',text}],{signal})
 try{
  row.names=[parent,sender,branch,target].map(agent=>service.namesOf(agent))
  if(['cold-creator','unreadable'].includes(action))await b.dispose()
  if(!['live','parent-direct','outside'].includes(action))await leaf.dispose()
  if(action==='provider-removed')await providerOwner.dispose()
  if(['sender-stale','root-replaced','unreadable'].includes(action)){
   query.observeSession=async function(id:any,options:any){if(action==='unreadable'&&id==='leaf')throw Error('history unavailable');const observation=await originalObserve.call(this,id,options);stale=true;return observation}
   if(action!=='unreadable')ctx.agents.get=function(id:any){if(stale&&id===(action==='sender-stale'?'a':'root'))return action==='sender-stale'?undefined:new Proxy(parent,{});return originalGet.call(this,id)}
  }
  if(action==='capacity'){service['config'].maxActiveSubagents[Symbol.for('cosmokit.volatile.write')](2);await send(sender,'b','resident')}
  if(action==='parent-direct'){await send(target,'b','direct');row.omitClosing=manager['resident'].get('leaf').omitClosingText}
  else if(action==='outside'){const outsider=(await ctx.agents.create({sessionId:'outside'})).agent;await send(outsider,'leaf','forbidden')}
  else{
   await send(sender,'leaf','cousin')
   if(action==='live'){
    await send(parent,'leaf','grandchild');await send(target,'root','grandparent')
    try{service.interrupt('leaf',{kind:'ancestor',agent:sender})}catch(error:any){row.interrupt=error.code}
    try{await send(sender,'a','self')}catch(error:any){row.self=error.code}
   }
   if(action==='cold-creator'){row.creatorLive=ctx.agents.get('b')!==undefined;row.resumedNames=service.namesOf(ctx.agents.get('leaf'))}
   row.accepted=true
  }
 }catch(error:any){row.error=error.code??null;process.stderr.write(action+': '+String(error.stack??error)+'\n')}
 finally{
  ctx.agents.get=originalGet;query.observeSession=originalObserve
  row.received=[...received];row.beforeDrain=[...manager['resident'].keys()].sort();await manager.drain()
  Object.assign(row,{resident:[...manager['resident'].keys()].sort(),slots:manager['rootPool'](parent)['slots'].size,reservations:manager['names']['pending'].size});await ctx.fiber.dispose()
 }rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
