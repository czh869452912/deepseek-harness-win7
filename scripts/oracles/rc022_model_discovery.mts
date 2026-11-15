import {join} from 'node:path'
import {readFileSync} from 'node:fs'
import {load,setup} from './rc022_subagent_fixture.mts'
const {registerListSubagentModels}=await load('packages/subagent/tool-subagent/src/list-models.ts'),{subagentModelSelectionProjectionDefinition:POLICY}=await load('packages/subagent/tool-subagent/src/model-selection-state.ts'),{ToolExecutionPipeline}=await load('packages/core/tools/src/pipeline.ts')
const {LlmAdapter}=await load('packages/llm/llm/src/index.ts')
class Adapter extends LlmAdapter{
 providerInfo(provider:string){return {id:provider,name:provider[0].toUpperCase()+provider.slice(1)}}
 async listModels(provider:string){return Promise.all(['fast','plain'].map(model=>this.resolveModel(provider,model)))}
 async resolveModel(provider:string,model:string){return {provider,id:model,name:model[0].toUpperCase()+model.slice(1),description:'Focused work.',...model==='plain'?{}:{reasoning:{efforts:[{id:'low',name:'Low'},{id:'high',name:'High',description:'Quality first.'}],defaultEffort:'high'}}}}
}
const Discovery={inject:['tools','sessionProjections'],async apply(ctx:any){registerListSubagentModels(ctx,await ctx.sessionProjections.register(POLICY))}}
const workspace=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source'),rows:any[]=[]
for(const input of JSON.parse(readFileSync(process.argv[4]!,'utf8'))){
 const {ctx,signal}=await setup(join(workspace,input.name)),row:any={name:input.name,results:[]}
 try{
  ctx.llm.registerAdapter(['alpha','beta'],new Adapter());const owner=await ctx.plugin(Discovery)
  const parent=(await ctx.agents.create({sessionId:'parent',agentOptions:input.parent??{provider:'alpha',model:'hidden'}})).agent
  if('routes'in input)parent.session.append('subagent/model-selection-policy',{allowedModels:input.routes})
  row.schemas=ctx.tools.schemas()
  const execute=async(args:any,agent:any)=>{
   const pipeline=new ToolExecutionPipeline(ctx),prepared=await pipeline.prepare({callId:'call',name:'list_subagent_models',arguments:args,agent,signal}),outcome=prepared.kind==='dispatch'?await pipeline.dispatch(prepared.exec):prepared,result=await pipeline.complete(prepared.exec,outcome)
   return {isError:result.isError===true,content:result.content,value:result.isError?null:result.value}
  }
  for(const request of input.requests)row.results.push(await execute(request,parent))
  row.noCaller=(await execute({},undefined)).content
  const definition=ctx.tools.get('list_subagent_models');try{await ctx.plugin(Discovery)}catch{}
  row.duplicatePreserved=ctx.tools.get('list_subagent_models')===definition
  await owner.dispose();row.released=ctx.tools.get('list_subagent_models')===undefined
 }finally{await ctx.fiber.dispose()}
 rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
