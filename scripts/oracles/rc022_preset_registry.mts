import {readFileSync} from 'node:fs'
import {pathToFileURL} from 'node:url'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),fixture=await setup(join(workspace,'source')),ctx=fixture.ctx,rows:any[]=[],agents:any[]=[]
const Loader=await load('vendor/loader/src/index.ts'),Registry=await load('packages/preset/agent-preset-registry/src/index.ts'),Delegation=await load('packages/subagent/tool-subagent/src/index.ts')
const {ToolExecutionPipeline}=await load('packages/core/tools/src/pipeline.ts')
try{
 ctx.baseUrl=pathToFileURL(workspace).href+'/'
 await ctx.plugin(Loader.default)
 ctx.loader.builtins['contribute']={name:'contribute',inject:['tools','systemPrompt'],apply(child:any,config:any){const name=config.tool;child.tools.register({name,description:'fixture tool '+name,parameters:{type:'object',properties:{},additionalProperties:false},execute:()=>Promise.resolve(name),output:{schema:{type:'string'},render:(_:any,value:any)=>[{type:'text',text:value}]}});child.systemPrompt.section({name:'preset:'+name,order:10,text:'section for '+name})}}
 await ctx.plugin(Registry.default,{default:'coding'})
 const presets=ctx.agentPresets,definition=(id:string,tool:string,extra:any={})=>({id,plugins:[{id:'tool',name:'cordis:contribute',config:{tool}}],...extra})
 const coding=await presets.register(definition('coding','coding_only',{name:'Coding',order:2})),reviewing=await presets.register(definition('reviewing','reviewing_only',{name:'Review',order:1}))
 rows.push({roster:await presets.remoteExportList(),resolve:await presets.resolve(),inventory:await presets.compositionInventory()})
 for(const value of [definition('coding','duplicate'),definition(' ','blank')]){try{await presets.register(value)}catch(error:any){rows.push({error:error.message})}}
 const bad=await presets.register({id:'bad',plugins:[null]});rows.push({broken:await presets.resolve('bad')});await bad()
 const parentHandle=await ctx.agents.create({sessionId:'parent',agentOptions:{provider:'script',model:'model'},setup:async(child:any)=>{await presets.mount(child,'coding')}}),parent=parentHandle.agent;agents.push(parentHandle)
 const visible=(agent:any)=>({preset:presets.composedPreset(agent.ctx)??null,tools:ctx.tools.schemas(agent).map((tool:any)=>tool.name)})
 rows.push({parent:visible(parent),compositions:presets.inspectCompositions().map((row:any)=>row.id)})
 const inheritedHandle=await ctx.agents.create({sessionId:'inherited',setup:async(child:any)=>{presets.composeFrom(child,parent.ctx)}}),inherited=inheritedHandle.agent;agents.push(inheritedHandle)
 rows.push({inherited:visible(inherited)})
 const lease=await presets.acquireScope('coding');await coding()
 rows.push({roster:await presets.list(),parent:visible(parent),inherited:visible(inherited),revisions:presets.inspectCompositions().map((row:any)=>row.id)})
 const codingNew=await presets.register(definition('coding','coding_v2')),newestHandle=await ctx.agents.create({sessionId:'newest',setup:async(child:any)=>{await presets.mount(child,'coding')}});agents.push(newestHandle)
 rows.push({parent:visible(parent),newest:visible(newestHandle.agent),revisions:presets.inspectCompositions().map((row:any)=>row.id)})
 rows.push({selected:await presets.select(parent,'reviewing'),stored:presets.presetForSession(parent.session),parent:visible(parent),inherited:visible(inherited)})
 const before=parent.session.snapshotEvents().length;await presets.select(parent,'reviewing');rows.push({selectionNoop:parent.session.snapshotEvents().length===before})
 await inheritedHandle.dispose();await lease[Symbol.asyncDispose]();await lease[Symbol.asyncDispose]();rows.push({revisions:presets.inspectCompositions().map((row:any)=>row.id)})
 const tool=await ctx.plugin(Delegation,{provider:'spawn',allowedAgentPresets:['coding','reviewing']})
 for(const [name,preset] of [['independent','coding'],['inherited',null]]){
  const args={name,prompt:'Task',description:'Focused task',...preset===null?{}:{agent_preset:preset}},pipeline=new ToolExecutionPipeline(ctx),prepared=await pipeline.prepare({callId:'call-'+name,name:'subagent',arguments:args,agent:parent,signal:fixture.signal}),outcome=prepared.kind==='dispatch'?await pipeline.dispatch(prepared.exec):prepared,result=await pipeline.complete(prepared.exec,outcome),child=ctx.agents.get(await fixture.service.resolveName(parent,name,fixture.signal))
  rows.push({delegated:result.value,child:visible(child),header:child.session.header.agentPreset??null})
 }
 await tool.dispose()
 const {MockAdapter,textResponse}=await load('packages/core/agent-loop/tests/mock-adapter.ts'),adapter=new MockAdapter([textResponse('recorded'),textResponse('recorded')]);ctx.llm.registerAdapter(['record'],adapter)
 for(const [name,preset] of [['model-selected','coding'],['model-inherited',null]]){
  const receipt=await fixture.service.startActivation({provider:'spawn',parent,name,label:'Model task',prompt:[{type:'text',text:'Task'}],signal:fixture.signal,delivery:'caller',agentOptions:{provider:'record',model:'model'},...preset===null?{}:{agentPreset:preset}}),result=await receipt.result;await receipt.dispose()
  rows.push({modelResult:result,modelTools:adapter.requests.at(-1).tools.map((tool:any)=>tool.name),promptContainsPresetSection:JSON.stringify(adapter.requests.at(-1).messages).includes('section for '+(preset?'coding_v2':'reviewing_only'))})
 }
 parent.session.append('turn/start',{turn:1})
 try{await presets.select(parent,'coding')}catch(error:any){rows.push({locked:{code:error.code,message:error.message,details:error.details}})}
 try{await presets.mount(ctx,'coding')}catch(error:any){rows.push({unscoped:error.message})}
 await reviewing();await codingNew();rows.push({roster:await presets.list(),remaining:presets.inspectCompositions().map((row:any)=>row.id)})
 ctx.loader.builtins.preset=(await load('packages/preset/agent-preset/src/index.ts')).default
 await ctx.loader.root.update([{id:'declared',name:'cordis:preset',config:{id:'declared',plugins:[{id:'expression',name:'cordis:contribute',config:{tool:{__jsExpr:"'declared_tool'"}}}]}}])
 rows.push({declared:await presets.resolve('declared'),preservedExpression:(await presets.readDocument('declared')).content.includes('!!js')})
 await ctx.loader.root.update([]);rows.push({declarationRemoved:!(await presets.list()).some((row:any)=>row.id==='declared')})
 const disposers=[];for(const id of ['Z','z','á','a','A','中'])disposers.push(await presets.register({id,plugins:[]}))
 rows.push({sortedIds:(await presets.list()).map((row:any)=>row.id)});for(const dispose of disposers)await dispose()
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
