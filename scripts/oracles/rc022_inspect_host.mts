import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{createScope}=await load('packages/core/scope/src/index.ts')
const Prompt=(await load('packages/core/system-prompt/src/index.ts')).default,Tools=(await load('packages/core/tools/src/index.ts')).default
const Executor=await load('packages/core/tool-executor-native/src/index.ts'),{CordisInspectRegistryService}=await load('packages/extensions/cordis-host-runner/src/inspect-registry.ts')
const Host=await load('packages/extensions/tool-cordis/src/host.ts'),Inspect=await load('packages/extensions/tool-cordis/src/index.ts'),{hostInspectProviders}=await load('packages/extensions/tool-cordis/src/providers.ts')
const ctx=new Context(),rows:any[]=[],scopes:any[]=[]
try{
 await ctx.plugin(Prompt);await ctx.plugin(Tools);await ctx.plugin(Executor);await ctx.plugin(CordisInspectRegistryService,10000)
 const host=ctx.plugin(Host);await host
 rows.push({stage:'mounted',providers:ctx.cordisInspect.list().map((row:any)=>row.id)})
 const definition=(name:string)=>({name,description:'fixture '+name,parameters:{type:'object',properties:{}},execute:async()=>({}),output:{schema:{type:'object'},render:()=>[]}})
 ctx.tools.register(definition('global_fixture'))
 const agents:any[]=[]
 for(const index of [0,1]){const agent:any={id:'agent-'+index},scope=createScope(ctx,agent);agent.ctx=scope.ctx;agents.push(agent);scopes.push(scope);await scope.ctx.plugin(Inspect)}
 const privateTool=(owner:any)=>owner.tools.register(definition('private_fixture'));privateTool.inject=['tools'];await scopes[0].ctx.plugin(privateTool)
 const signal=new AbortController().signal
 for(const agent of agents){const value=await ctx.cordisInspect.query('host','Tool','listTools',{},agent,signal);rows.push({stage:'tool-view',agent:agent.id,tools:value.tools.map((row:any)=>row.name)})}
 const agent=agents[0],tool=ctx.tools.get('cordis_inspect_query',agent)
 const value=await tool.execute({platform:'host',provider:'Service',method:'listService',input:{service:'tools'}},{agent,signal})
 rows.push({stage:'tool-query',platform:value.platform,provider:value.provider,method:value.method,mode:value.data.mode,key:value.data.service.key,types:value.data.referencedTypes.length})
 for(const provider of hostInspectProviders(ctx)){try{await provider.query('wrong',{}, {agent,signal})}catch(error:any){rows.push({stage:'wrong-method',provider:provider.manifest.id,error:error.message})}}
 try{ctx.cordisInspect.register(hostInspectProviders(ctx)[0])}catch(error:any){rows.push({stage:'duplicate',error:error.message})}
 try{await ctx.cordisInspect.query('host','Config','listConfigs',{},agent,signal)}catch(error:any){rows.push({stage:'config-no-loader',error:error.message})}
 await scopes[0].dispose()
 rows.push({stage:'first-scope-disposed',providers:ctx.cordisInspect.list().map((row:any)=>row.id),first:ctx.tools.schemas(agents[0]).map((row:any)=>row.name),second:ctx.tools.schemas(agents[1]).map((row:any)=>row.name)})
 await host.dispose()
 rows.push({stage:'host-disposed',providers:ctx.cordisInspect.list(),tools:ctx.tools.schemas(agents[1]).map((row:any)=>row.name)})
}finally{for(const scope of scopes)await scope.dispose();await ctx.fiber.dispose()}
console.log(JSON.stringify(rows))
