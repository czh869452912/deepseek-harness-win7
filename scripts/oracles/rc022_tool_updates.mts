import {resolve} from 'node:path'
import {readFileSync} from 'node:fs'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {projectToolUpdates}=await load('packages/llm/llm/src/content.ts'),{ToolHistoryProjection}=await load('packages/core/session/src/tool-history.ts'),rows:any[]=[]
for(const c of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const row:any={kind:c.kind,action:c.action}
 if(c.kind==='project'){row.mode=c.mode;const before=JSON.stringify(c),result=projectToolUpdates(c.messages,c.tools,c.mode??undefined,c.history??undefined);Object.assign(row,{result,sameMessages:result.messages===c.messages,sameTools:result.tools===c.tools,unchanged:JSON.stringify(c)===before})}
 else{const fold=new ToolHistoryProjection(),snapshots:any[]=[];try{for(const event of c.events){fold.apply(event);snapshots.push(fold.snapshot())}row.snapshots=snapshots;row.repeat=fold.snapshot()===fold.snapshot()}catch(error:any){row.error=error.message}}
 rows.push(row)
}
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Store}=await load('packages/core/session/src/index.ts'),{default:Registry}=await load('packages/session/session-projection/src/index.ts'),{default:Agents}=await load('packages/core/agent/src/index.ts'),{default:Loop}=await load('packages/core/agent-loop/src/index.ts'),{default:Prompt}=await load('packages/core/system-prompt/src/index.ts'),{default:Tools}=await load('packages/core/tools/src/index.ts'),Native=await load('packages/core/tool-executor-native/src/index.ts'),{default:Llm,createUserMessage}=await load('packages/llm/llm/src/index.ts'),{MockAdapter,textResponse}=await load('packages/core/agent-loop/tests/mock-adapter.ts')
for(const mode of [undefined,'in-history','addition-only']){
 const ctx=new Context(),requests:any[]=[],errors:string[]=[];let handle:any
 try{
  for(const plugin of [Llm,Store,Registry,Prompt,Tools,Native,Agents])await ctx.plugin(plugin);await ctx.plugin(Loop,{agents:[]})
  ctx.on('agent/error',(value:any)=>errors.push(value.error.message))
  const adapter=new MockAdapter(Array.from({length:7},()=>textResponse('ok')));adapter.toolUpdate=mode
  const stream=adapter.stream.bind(adapter);adapter.stream=(request:any)=>{requests.push({tools:request.tools??[],updates:request.messages.filter((m:any)=>m.role==='developer').map((m:any)=>m.content),history:[request.toolHistory.tools.length,request.toolHistory.updates.length]});return stream(request)}
  ctx.llm.registerAdapter(['script'],adapter)
  const tool=(name:string,description=name+' tool')=>ctx.tools.register({name,description,parameters:{},output:{schema:{type:'string'},render:()=>[]},execute:()=> 'done'});let removeA=tool('search'),removeB:any
  handle=await ctx.agents.create({sessionId:'updates',agentOptions:{provider:'script',model:'model'}});const agent=handle.agent
  for(let step=0;step<7;step++){if(step===1)removeB=tool('fetch');if(step===2)removeA();if(step===3)removeA=tool('search');if(step===4){removeB();removeB=tool('fetch','changed')}if(step===5)adapter.toolUpdate=mode===undefined?'in-history':undefined;agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:'step-'+step}]}));await agent.whenIdle()}
  const events=agent.session.snapshotEvents(),headers=events.filter((e:any)=>e.type==='request/header'),updates=events.filter((e:any)=>e.type==='developer/message');rows.push({kind:'driver',mode:mode??null,requests,errors,restored:JSON.stringify((await load('packages/core/session/src/index.ts')).Session.create('restored',events).toolHistory())===JSON.stringify(agent.session.toolHistory()),cached:agent.session.toolHistory()===agent.session.toolHistory(),headers:headers.map((e:any)=>({reason:e.data.reason,series:e.data.startsSeries??false,tools:(e.data.header.tools??[]).map((t:any)=>t.name)})),additions:updates.map((e:any)=>({content:e.data.message.content,bound:e.data.headerSeq===undefined?null:headers.findIndex((h:any)=>h.seq===e.data.headerSeq)})),endings:events.filter((e:any)=>e.type==='turn/end').map((e:any)=>e.data.reason.kind)})
 }finally{if(handle)await handle.dispose();await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
