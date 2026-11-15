import {resolve,join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href),workspace=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source')
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Loop}=await load('packages/core/agent-loop/src/index.ts'),Backend=await load('packages/session/session-persistence-jsonl/src/index.ts'),{default:Manager}=await load('packages/subagent/subagent/src/manager.ts')
const {subagentCatalogProjectionDefinition:CATALOG}=await load('packages/subagent/subagent/src/catalog.ts'),{subagentIdentityProjectionDefinition:IDENTITY,subagentTimingProjectionDefinition:TIMING}=await load('packages/subagent/subagent/src/projection.ts')
const {TestSessionQuery}=await load('packages/subagent/subagent/tests/test-session-query.ts'),{MockAdapter,textResponse}=await load('packages/core/agent-loop/tests/mock-adapter.ts'),fork=await load('packages/subagent/subagent-fork-in-process/src/index.ts'),plugins:any[]=[],rows:any[]=[]
for(const path of ['packages/llm/llm/src/index.ts','packages/core/session/src/index.ts','packages/session/session-projection/src/index.ts','packages/core/system-prompt/src/index.ts','packages/core/tools/src/index.ts','packages/core/tool-executor-native/src/index.ts','packages/core/agent/src/index.ts']){const module=await load(path);plugins.push(module.default??module)}
for(const action of ['fresh','fork','resume','prepare-failure','catalog-failure','directory-failure','capacity','external']){
 const ctx=new Context(),edges:any[]=[],captured:any[]=[];for(const plugin of plugins)await ctx.plugin(plugin)
 await ctx.plugin(Backend,{root:join(workspace,action),compression:'none'});await ctx.plugin(Loop,{agents:[]});ctx.llm.registerAdapter(['script'],new MockAdapter(Array.from({length:5},()=>textResponse('answer'))))
 const catalog=await ctx.sessionProjections.register(CATALOG),identity=await ctx.sessionProjections.register(IDENTITY);await ctx.sessionProjections.register(TIMING);await ctx.plugin(TestSessionQuery)
 ctx.provide('workingDirectory');ctx.workingDirectory={ensure:async(_agent:any,signal:AbortSignal)=>{signal.throwIfAborted();return 'C:/rc022-work'},set:async(_agent:any,path:string,signal:AbortSignal)=>{signal.throwIfAborted();if(action==='directory-failure')throw Error('directory failed');return path}}
 const parent=(await ctx.agents.create({sessionId:'parent',agentOptions:{provider:'script',model:'model'}})).agent
 const emit=(event:string,info:any)=>{edges.push({event,id:info.id,local:info.local,...info.stopReason===undefined?{}:{stopReason:info.stopReason}});if(event==='subagent/start'&&info.local){const child=ctx.agents.get(info.id);captured.push({published:child!==undefined,own:child.session.isOwnSeq(identity.stateOf(child.session).identity.seq),inherited:child.session.inheritedEventCount})}}
 let manager:any;await ctx.inject(['agents'],childCtx=>{manager=new Manager(childCtx,{identityOf:(session:any)=>identity.stateOf(session).identity,catalogOf:(session:any)=>CATALOG.wire.view(catalog.stateOf(session)),emitLifecycle:emit},()=>1)});const row:any={action},original=parent.session.append
 let held:any
 try{
  if(action==='fork'){parent.session.append('turn/start',{turn:1});parent.session.append('turn/end',{turn:1,reason:{kind:'completed'}});parent.session.append('turn/start',{turn:2})}
  let forkProvider:any;fork.apply({subagents:{registerProvider:(provider:any)=>forkProvider=provider}},{providerName:'local'})
  const prepare=async(request:any)=>{if(action==='prepare-failure')throw Error('prepare failed');return action==='fork'?forkProvider.prepareContinuable(request):{}}
  if(action==='catalog-failure')parent.session.append=function(type:string,...args:any[]){if(type==='subagent/catalog')throw Error('catalog failed');return original.call(this,type,...args)}
  if(action==='capacity')held=manager['rootPool'](parent).reserve(1)
  const spec={provider:'local',parent,childId:'child',name:'worker',label:'Task',prompt:[{type:'text',text:'task'}],signal:new AbortController().signal,delivery:'caller'};let receipt:any
  if(action==='external'){const completion=Promise.withResolvers();receipt=await manager.startExternal({...spec,delivery:'parent'},async()=>({id:'external',result:completion.promise,dispose:async()=>{}}));completion.resolve({output:[{type:'text',text:'remote'}],stopReason:'completed'})}
  else receipt=await manager.startLocal(spec,prepare)
  row.receipt={childId:receipt.childId,name:receipt.name,message:'messageId'in receipt};row.result=await receipt.result
  if(action==='resume'){if(ctx.agents.get('child')!==undefined)throw Error('child should be cold');row.resolved=await (await load('packages/subagent/subagent/src/index.ts')).default.prototype.resolveName.call({ctx,rootOf:(caller:any)=>manager.rootOf(caller)},parent,'worker',new AbortController().signal);await manager.sendMessage(parent,'child',[{type:'text',text:'again'}],{signal:new AbortController().signal});await manager.waitForTreeWork(parent)}
  if(action!=='external'){using observation=await ctx.sessionQuery.observeSession('child',{});row.descriptors=observation.events.filter((event:any)=>event.type==='subagent/descriptor').map((event:any)=>event.data);row.turns=observation.events.filter((event:any)=>event.type==='turn/end').map((event:any)=>event.data.reason.kind)}
 }catch(error:any){row.error=error.code??null;process.stderr.write(action+': '+String(error.stack??error)+'\n')}
 finally{
  parent.session.append=original;held?.();await manager.drain();row.catalog=CATALOG.wire.view(catalog.stateOf(parent.session)).map((entry:any)=>Object.fromEntries(['id','name','mode','label'].filter(key=>key in entry).map(key=>[key,entry[key]])))
  Object.assign(row,{edges,captured,resident:[...manager['resident'].keys()],childLive:ctx.agents.get('child')!==undefined,reservations:manager['names']['pending'].size,slots:manager['rootPool'](parent)['slots'].size});await ctx.fiber.dispose()
 }rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
