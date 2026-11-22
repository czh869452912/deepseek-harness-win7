import {readFileSync,mkdirSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const base=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source'),project=join(base,'project'),nested=join(project,'pkg'),home=join(base,'home'),shared=join(base,'shared')
for(const path of [nested,home,shared])mkdirSync(path,{recursive:true})
const write=(path:string,text:string)=>writeFileSync(path,text)
for(const [path,text] of [[join(project,'.git'),'marker'],[join(project,'AGENTS.md'),'project rules'],[join(nested,'AGENTS.md'),'nested rules'],[join(nested,'file.txt'),'content'],[join(home,'AGENTS.md'),'global rules'],[join(shared,'AGENTS.md'),'shared rules']])write(path!,text!)
const saved={DSH_HOME:process.env.DSH_HOME,DSH_AGENTS_HOME:process.env.DSH_AGENTS_HOME};process.env.DSH_HOME=home;process.env.DSH_AGENTS_HOME=shared
const fixture=await setup(join(base,'sessions'),project),{ctx}=fixture,rows:any[]=[],{createUserMessage}=await load('packages/llm/llm/src/index.ts'),{agentEvents}=await load('packages/core/agent/src/index.ts'),{ToolExecutionPipeline}=await load('packages/core/tools/src/pipeline.ts')
let handle:any,counter=0
try{
 const toolFs=await load('packages/fs/tool-fs/src/index.ts');await ctx.plugin(toolFs.default??toolFs)
 const plugin=await ctx.plugin(await load('packages/context/agent-instructions/src/index.ts'),{maxBytes:65536})
 handle=await ctx.agents.create({sessionId:'runtime',meta:{cwd:project},agentOptions:{provider:'script',model:'model'}})
 const agent=handle.agent,dispatch=agentEvents(ctx,agent),user=(text:string)=>createUserMessage({content:[{type:'text',text}],source:{kind:'user'}})
 const clean=(value:any):any=>Array.isArray(value)?value.map(clean):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).filter(([key])=>key!=='id').map(([key,item])=>[key,clean(item)])):value
 const pending=()=>agent.inbox.nextStep.filter((message:any)=>message.source.kind==='agent-instructions')
 async function step(label:string,claimed:any[]=[],kind='reject',stepNumber=1){
  const decision={kind,...kind!=='reject'?{messages:[...claimed,user('driver')],startsRequestSeries:true}:{}}
  const result=await dispatch.waterfall('agent/pre-step',{turn:1,step:stepNumber,messages:claimed,signal:fixture.signal},async()=>decision)
  rows.push({name:label,decision:clean(result),pending:clean(pending())});return result
 }
 await step('rejected-first');const first=pending()[0];await step('rejected-reuses-pending');rows.push({name:'pending-identity',same:pending()[0]===first})
 const entered=await step('entered-order',[user('direct')],'enter');for(const message of entered.messages)agent.session.append('user/message',message,{surfaceOp:'append'})
 await step('already-visible',[],'enter')
 async function call(name:string,args:any,parent?:any){const pipeline=new ToolExecutionPipeline(ctx),prepared=await pipeline.prepare({callId:'call-'+String(++counter),name,arguments:args,agent,signal:fixture.signal,...parent===undefined?{}:{parent}}),outcome=prepared.kind==='dispatch'?await pipeline.dispatch(prepared.exec):prepared;return pipeline.complete(prepared.exec,outcome)}
 await call('read',{file_path:join('pkg','file.txt')});await step('idle-tool-touch')
 function appendPending(){for(const message of pending()){agent.session.append('user/message',message,{surfaceOp:'append'});agent.inbox.remove(message.id)}}
 appendPending();agent.session.append('turn/start',{turn:1});agent.session.append('step/start',{turn:1,step:1})
 write(join(nested,'AGENTS.md'),'nested changed during step');let result=await call('read',{file_path:join('pkg','file.txt')});await Promise.resolve()
 rows.push({name:'open-step-defers',pending:clean(pending()),isError:result.isError});agent.session.append('step/end',{turn:1,step:1});await step('closed-step-projects');appendPending()
 const inside:number[]=[]
 ctx.tools.register({name:'outer',description:'',parameters:{type:'object'},output:{schema:{type:'string'},render:(_a:any,v:any)=>[{type:'text',text:v}]},execute:async(_args:any,execution:any)=>{await call('read',{file_path:join('pkg','file.txt')},execution.token);await Promise.resolve();inside.push(pending().length);throw Error('outer failed after successful child')}})
 write(join(nested,'AGENTS.md'),'nested changed in successful child of failed outer');result=await call('outer',{});await step('outer-completion-projects-child');rows.push({name:'parent-boundary',inside,outerError:result.isError});appendPending()
 write(join(nested,'AGENTS.md'),'failed read must not project this');await call('read',{file_path:join('pkg','missing.txt')});await Promise.resolve();rows.push({name:'failed-tool-no-projection',pending:clean(pending())})
 await ctx.workingDirectory.set(agent,'pkg',fixture.signal);await step('directory-replacement');rows.push({name:'header-preserved',cwd:agent.session.header.cwd,current:ctx.workingDirectory.get(agent.session)})
 appendPending();for(const name of ['alpha','beta']){mkdirSync(join(nested,name));write(join(nested,name,'AGENTS.md'),name+' nested rule');write(join(nested,name,'file.txt'),'content')}
 const betaReady = Promise.withResolvers<void>()
 const alphaCommitted = Promise.withResolvers<void>()
 const alphaPath = join('alpha','file.txt')
 const betaPath = join('beta','file.txt')
 // Hold the results until both reads are in flight, then commit alpha first.
 const unhook = ctx.on('tools/post-execute', async (execution, _result, next) => {
  if (execution.name === 'read' && execution.arguments.file_path === alphaPath) {
   await betaReady.promise
  } else if (execution.name === 'read' && execution.arguments.file_path === betaPath) {
   betaReady.resolve()
   await alphaCommitted.promise
  }
  return next()
 })
 try {
  const alpha = call('read', {file_path: alphaPath}).then(result => {
   alphaCommitted.resolve()
   return result
  })
  const results = await Promise.all([alpha, call('read', {file_path: betaPath})])
  if (results.some(result => result.isError)) throw new Error('Concurrent fixture read failed')
 } finally {
  unhook()
 }
 await step('serialized-concurrent-projections')
 await plugin.dispose();const before=agent.session.snapshotEvents().length;await call('read',{file_path:'file.txt'});await Promise.resolve();rows.push({name:'unloaded-no-projection',inboxEvents:agent.session.snapshotEvents().slice(before).filter((event:any)=>event.type==='agent/inbox/spliced').length})
}finally{if(handle)await handle.dispose();await ctx.fiber.dispose();for(const [key,value] of Object.entries(saved)){if(value===undefined)delete process.env[key];else process.env[key]=value}}
const normalize=(value:any):any=>typeof value==='string'&&value.includes(project)?value.replaceAll(project,'<work>'):Array.isArray(value)?value.map(normalize):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)])):value
process.stdout.write(JSON.stringify(normalize(rows)))
