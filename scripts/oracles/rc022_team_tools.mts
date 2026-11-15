import {join} from 'node:path'
import {readFileSync} from 'node:fs'
import {load,setup} from './rc022_subagent_fixture.mts'
import {collect} from './rc022_team_tool_metadata.mts'
const {default:Team}=await load('packages/team/agent-team/src/index.ts'),Tools=await load('packages/team/tool-agent-team/src/index.ts'),{ToolExecutionPipeline}=await load('packages/core/tools/src/pipeline.ts'),{scopeOf}=await load('packages/core/scope/src/index.ts')
const workspace=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source'),fixture=await setup(workspace),{ctx,signal}=fixture,rows:any[]=[{kind:'metadata',data:collect()}]
try{
 await ctx.plugin(Team);const owner=await ctx.plugin(Tools),parent=(await ctx.agents.create({sessionId:'root',agentOptions:{provider:'script',model:'model'}})).agent
 const receipt=await fixture.service.startActivation({provider:'spawn',parent,childId:'child',name:'worker',label:'Task',prompt:[{type:'text',text:'Task'}],signal,delivery:'caller'}),worker=ctx.agents.get('child'),actors:any={root:parent,worker,none:undefined},inbox:any[]=[]
 ctx.on('agent/inbox/inserted',({agent}:any)=>inbox.push(agent.id))
 const resolved=(agent:any)=>ctx.tools.resolve({agent,signal,modelSelection:{provider:'script',model:'model'}})
 const execute=async(name:string,args:any,agent:any,toolSet?:any)=>{
  const owned=toolSet===undefined;if(owned)toolSet=await resolved(agent)
  try{
   const pipeline=new ToolExecutionPipeline(ctx),prepared=await pipeline.prepare({callId:'call',name,arguments:args,agent,signal,toolSet}),outcome=prepared.kind==='dispatch'?await pipeline.dispatch(prepared.exec):prepared,result=await pipeline.complete(prepared.exec,outcome)
   return {isError:result.isError===true,content:result.content,value:result.isError?null:result.value}
  }finally{if(owned)toolSet.dispose()}
 }
 for(const command of JSON.parse(readFileSync(process.argv[4]!,'utf8'))){
  const {op}=command,agent=actors[command.caller??'root'],row:any={op}
  if(op==='visible'){const toolSet=await resolved(agent);try{row.names=ctx.tools.schemas(agent,toolSet).filter((tool:any)=>tool.name.startsWith('team_')).map((tool:any)=>tool.name).sort()}finally{toolSet.dispose()}}
  else if(op==='prompt'){const assembly=await ctx.systemPrompt.assemble({agent,scope:agent===undefined?undefined:scopeOf(agent.ctx)});row.policy=assembly.sections.find((s:any)=>s.name==='team:policy')?.text??''}
  else if(op==='enable')await ctx.agentTeams.setEnabled(parent,command.value,signal)
  else if(op==='execute')Object.assign(row,await execute(command.name,command.args,agent))
  else if(op==='held-disable'){const toolSet=await resolved(parent);try{await ctx.agentTeams.setEnabled(parent,false,signal);Object.assign(row,await execute('team_task_get',{task_id:'task-1'},parent,toolSet))}finally{toolSet.dispose()}}
  else if(op==='cold')await receipt.dispose()
  else if(op==='unload')await owner.dispose()
  else if(op==='removed-config'){try{await ctx.plugin(Tools,{freshProvider:'spawn'})}catch(error:any){row.error=String(error.message)}}
  rows.push(row)
 }
 rows.push({op:'effects',inbox,tasks:ctx.agentTeams.listTasks(parent)})
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
