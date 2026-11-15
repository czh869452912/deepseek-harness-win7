import {join} from 'node:path'
import {readFileSync} from 'node:fs'
import {load,setup} from './rc022_subagent_fixture.mts'
const {default:Settings}=await load('packages/subagent/tool-subagent/src/model-selection-settings.ts')
const {subagentModelSelectionProjectionDefinition:POLICY,subagentModelSelectionPolicy:readPolicy}=await load('packages/subagent/tool-subagent/src/model-selection-state.ts')
const {createVolatile}=await load('vendor/cosmokit/src/index.ts')
const workspace=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source'),rows:any[]=[]
for(const input of JSON.parse(readFileSync(process.argv[4]!,'utf8'))){
 const {ctx}=await setup(join(workspace,input.name)),row:any={name:input.name,results:[]},agents:any={},handles:any={}
 try{
  const owner=await ctx.plugin(Settings,input.config??{}),refs=owner['_effectiveConfig'],policy=await ctx.sessionProjections.register(POLICY)
  const snapshot=(agent:any)=>({policy:readPolicy(policy,agent.session)??null,policies:agent.session.snapshotEvents().filter((e:any)=>e.type==='subagent/model-selection-policy').length})
  for(const command of input.commands){try{
   const {op,id}=command;let result:any
   if(op==='settings'){for(const key of Object.keys(refs))if(key in command)refs[key][Symbol.for('cosmokit.volatile.write')](createVolatile(command[key]).get());result={updated:true}}
   else if(op==='unload'){await owner.dispose();result={released:ctx.subagentModelSelection===undefined}}
   else if(op==='read')result=snapshot(agents[id])
   else{
    const request:any={sessionId:id,agentOptions:{provider:'script',model:'model'}};let handle:any
    if(op==='resume'){agents[id].session.append('session/title',{title:'Saved',messageSeqs:[],source:{kind:'user'}});await ctx.sessions.flush(agents[id].session);await handles[id].dispose();handle=await ctx.agents.resume({resumeSessionId:id})}
    else{
     if('parent' in command)request.meta={parentSession:command.parent,origin:'subagent'}
     if('seed' in command)request.seed=agents[command.seed].session.snapshotEvents()
     if('policy' in command)request.setup=async(_ctx:any,agent:any)=>{agent.session.append('subagent/model-selection-policy',{allowedModels:command.policy})}
     handle=await ctx.agents.create(request)
    }
    handles[id]=handle;agents[id]=handle.agent;result=snapshot(handle.agent)
   }
   row.results.push(result)
  }catch(error:any){row.results.push({error:error.message??String(error)})}}
  row.agents=ctx.agents.list().map((agent:any)=>agent.id)
 }finally{await ctx.fiber.dispose()}
 rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
