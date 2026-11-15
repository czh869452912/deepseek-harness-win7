import {join} from 'node:path'
import {readFileSync} from 'node:fs'
import {load,setup} from './rc022_subagent_fixture.mts'
import {collect} from './rc022_control_tool_metadata.mts'
const Tools=await load('packages/subagent/tool-subagent-control/src/index.ts'),{ToolExecutionPipeline}=await load('packages/core/tools/src/pipeline.ts'),{scopeOf}=await load('packages/core/scope/src/index.ts'),{createUserMessage}=await load('packages/llm/llm/src/index.ts')
const fixture=await setup(join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source')),{ctx,signal}=fixture,rows:any[]=[{kind:'metadata',data:collect()}],handles:any[]=[]
const root=async(id:string)=>{const handle=await ctx.agents.create({sessionId:id,agentOptions:{provider:'script',model:'model'}});handles.push(handle);return handle.agent}
const child=async(parent:any,id:string)=>{const receipt=await fixture.service.startActivation({provider:'spawn',parent,childId:id,name:id,label:id+' task',prompt:[{type:'text',text:'Task'}],signal,delivery:'caller'}),agent=ctx.agents.get(id);while(agent.status!=='running')await new Promise(r=>setTimeout(r,1));return [receipt,agent]}
const execute=async(name:string,args:any,agent:any,rootCallId='root-call',callerSignal=signal)=>{
 const pipeline=new ToolExecutionPipeline(ctx),prepared=await pipeline.prepare({callId:'call',name,arguments:args,agent,rootCallId,signal:callerSignal}),outcome=prepared.kind==='dispatch'?await pipeline.dispatch(prepared.exec):prepared,result=await pipeline.complete(prepared.exec,outcome)
 let value=result.isError?null:result.value;if(value&&typeof value==='object'&&'messageId'in value)value={messageId:'<message>'}
 return {isError:result.isError===true,content:result.content,value}
}
const identity=async(agent:any)=>{const assembly=await ctx.systemPrompt.assemble({agent,scope:agent===undefined?undefined:scopeOf(agent.ctx)});return assembly.contexts.find((c:any)=>c.name==='subagent:identity')?.text??''}
try{
 let owner=await ctx.plugin(Tools)
 const parent=await root('root'),[a,sender]=await child(parent,'a'),[b,branch]=await child(parent,'b'),[leaf,target]=await child(branch,'leaf')
 for(const agent of [parent,sender,target,undefined])rows.push({kind:'identity',id:agent?.id??null,text:await identity(agent)})
 for(const [agent,name,args]of [[parent,'list_agents',{}],[sender,'list_agents',{}],[sender,'send_message',{agent:'b/leaf',message:'cousin'}],[target,'send_message',{agent:'lead',message:'result'}],[sender,'interrupt_agent',{agent:'b/leaf'}],[parent,'interrupt_agent',{agent:'missing'}],[sender,'send_message',{agent:'a',message:'self'}],[sender,'send_message',{agent:'missing/path',message:'missing'}],[undefined,'list_agents',{}]] as any[])rows.push({kind:'call',tool:name,result:await execute(name,args,agent)})
 await leaf.dispose();await b.dispose();rows.push({kind:'call',tool:'list_agents',result:await execute('list_agents',{},parent)})
 await a.dispose();rows.push({kind:'identity',id:'a',text:await identity(sender)})
 for(const value of [9999,3600001,1.5])rows.push({kind:'invalid-wait',result:await execute('wait_agent',{timeout_ms:value},parent)})
 rows.push({kind:'missing-wait',result:await execute('wait_agent',{},undefined)})
 const timers:any[]=[],realSet=globalThis.setTimeout,realClear=globalThis.clearTimeout
 globalThis.setTimeout=((callback:any,ms:number,...args:any[])=>{if(ms<10000)return realSet(callback,ms,...args);const timer={active:true,callback:()=>callback(...args),owned:true};timers.push(timer);return timer}) as any
 globalThis.clearTimeout=((timer:any)=>{if(timer?.owned)timer.active=false;else realClear(timer)}) as any
 const inject=(agent:any,text:string)=>agent.inject(createUserMessage({content:[{type:'text',text}]}))
 const hooks=()=>['agent/inbox/inserted','agent/disposed'].flatMap(name=>ctx.events._hooks[name]??[])
 const pending=async(agent:any,rootCallId='wait-call',callerSignal=signal)=>{
  const before=new Set(hooks())
  const task:any={done:false,promise:execute('wait_agent',{timeout_ms:10000},agent,rootCallId,callerSignal)};task.promise.finally(()=>task.done=true)
  for(let i=0;i<1000;i++){await new Promise(setImmediate);if(task.done||timers.some(t=>t.active)){task.hooks=hooks().filter(hook=>!before.has(hook));return task}}
  throw Error('wait did not subscribe')
 }
 const record=async(name:string,task:any)=>{const result=await task.promise;rows.push({kind:'wait',name,result,timers:timers.filter(t=>t.active).length,listenersReleased:task.hooks.every((hook:any)=>!hooks().includes(hook))})}
 try{
  inject(parent,'first');await record('pending',await pending(parent))
  let task=await pending(parent);for(const timer of [...timers])if(timer.active)timer.callback();await record('same-call-timeout',task)
  inject(parent,'second');await record('new-input-same-call',await pending(parent));await record('new-call-pending',await pending(parent,'different-call'))
  parent.inbox.clear();task=await pending(parent);inject(parent,'arrived');await record('arrival',task)
  parent.inbox.clear();const outsider=await root('outsider');task=await pending(parent);inject(outsider,'unrelated');await new Promise(setImmediate);rows.push({kind:'unrelated',pending:!task.done});inject(parent,'mine');await record('unrelated-then-own',task)
  parent.inbox.clear();const controller=new AbortController();task=await pending(parent,'wait-call',controller.signal);controller.abort(Error('caller aborted'));await record('cancel',task)
  parent.inbox.clear();task=await pending(parent);await handles[0].dispose();await record('disposed',task)
  outsider.inbox.clear();task=await pending(outsider);await owner.dispose();await record('unloaded',task)
  globalThis.setTimeout=realSet;globalThis.clearTimeout=realClear
  owner=await ctx.plugin(Tools,{interrupt:false});rows.push({kind:'optional',names:ctx.tools.schemas().filter((t:any)=>['list_agents','send_message','wait_agent','interrupt_agent'].includes(t.name)).map((t:any)=>t.name).sort()})
  await owner.dispose();rows.push({kind:'removed',text:await identity(outsider)})
 }finally{globalThis.setTimeout=realSet;globalThis.clearTimeout=realClear}
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
