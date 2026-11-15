import {join} from 'node:path'
import {readFileSync} from 'node:fs'
import {load,setup} from './rc022_subagent_fixture.mts'
import {collect} from './rc022_delegation_metadata.mts'
const Tool=await load('packages/subagent/tool-subagent/src/index.ts'),Spawn=await load('packages/subagent/subagent-spawn-in-process/src/index.ts'),Fork=await load('packages/subagent/subagent-fork-in-process/src/index.ts'),{ToolExecutionPipeline}=await load('packages/core/tools/src/pipeline.ts'),{scopeOf}=await load('packages/core/scope/src/index.ts')
const workspace=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source'),rows:any[]=[{kind:'metadata',value:{fresh:await collect(),inherited:await collect(true)}}]
for(const input of JSON.parse(readFileSync(process.argv[4]!,'utf8'))){
 const fixture=await setup(join(workspace,input.name)),{ctx,signal}=fixture,row:any={name:input.name,results:[]},config={provider:'spawn',...input.config};let providerOwner=fixture.provider,owner:any
 try{
  if(config.provider==='fork')providerOwner=await ctx.plugin(Fork)
  owner=await ctx.plugin(Tool,config)
  const parent=(await ctx.agents.create({sessionId:'parent',agentOptions:{provider:'script',model:'model'}})).agent
  for(const command of input.commands){try{
   const op=command.op,caller=command.caller??'root',agent=caller==='none'?undefined:caller==='root'?parent:ctx.agents.get(await fixture.service.resolveName(parent,caller,signal));let result:any
   if(op==='view'){
    const assembly=await ctx.systemPrompt.assemble({agent,scope:agent===undefined?undefined:scopeOf(agent.ctx)})
    result={schemas:ctx.tools.schemas(agent),sections:assembly.sections.filter((p:any)=>p.name.startsWith('tool:')).map((p:any)=>({name:p.name,text:p.text})),depth:assembly.contexts.filter((p:any)=>p.name.endsWith(':depth')).map((p:any)=>({name:p.name,text:p.text}))}
   }else if(op==='call'){
    const pipeline=new ToolExecutionPipeline(ctx),prepared=await pipeline.prepare({callId:'call',name:'subagent',arguments:command.args,agent,signal}),outcome=prepared.kind==='dispatch'?await pipeline.dispatch(prepared.exec):prepared,value=await pipeline.complete(prepared.exec,outcome)
    result={isError:value.isError===true,content:value.content,value:value.isError?null:value.value}
   }else if(op==='depth'){fixture.service['config'].maxDepth[Symbol.for('cosmokit.volatile.write')](command.value);result={updated:true}}
   else if(op==='remove'){await providerOwner.dispose();result={removed:true}}
   else if(op==='add'){providerOwner=await ctx.plugin(Spawn,{providerName:'late'});result={added:true}}
   else if(op==='sibling'){await ctx.plugin(Tool,{provider:'spawn',toolName:'other'});result={added:true}}
   else if(op==='unload'){await owner.dispose();result={unloaded:true}}
   else if(op==='bad-provider'){fixture.service.registerProvider({name:'late',capabilities:{},inheritsParentContext:false,prepareContinuable:async()=>({})});result={registered:true}}
   else throw Error('unknown command')
   row.results.push(result)
  }catch(error:any){row.results.push({error:error.message??String(error)})}}
 }catch(error:any){row.error=error.message??String(error)}
 finally{await ctx.fiber.dispose()}
 rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
