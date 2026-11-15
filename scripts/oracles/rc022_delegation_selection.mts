import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href),models=await load('packages/subagent/tool-subagent/src/model-selection.ts'),{SubagentPresetSelection}=await load('packages/subagent/tool-subagent/src/preset-selection.ts'),{subagentModelSelectionProjectionDefinition:POLICY}=await load('packages/subagent/tool-subagent/src/model-selection-state.ts'),rows:any[]=[]
for(const input of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const row:any={kind:input.kind}
 try{
  if(input.kind==='model'){
   const configured=input.configured??undefined,value=models.requestedAgentOptions(configured,input.request,input.enabled,input.policy??undefined,input.parent)
   Object.assign(row,{value:value??null,same:value===configured,hasRequest:models.hasDelegationModelRequest(input.request),configured:models.hasConfiguredLlmSelection(configured),cleared:value!==undefined&&Object.hasOwn(value,'reasoningEffort')&&value.reasoningEffort===undefined})
  }else if(input.kind==='preflight'){
   const calls:any[]=[];await models.preflightChildLlmRoute({resolveCallConfig:async(route:any)=>calls.push(route)},input.parent,input.requested??undefined,undefined,input.inherit);row.calls=calls
  }else if(input.kind==='routes'){models.assertAllowedModelRoutes(input.routes);row.accepted=true}
  else if(input.kind==='checkpoint')row.accepted=POLICY.stateSchema.safeParse(input.value).success
  else{
   const selection=new SubagentPresetSelection(input.config);Object.assign(row,{configured:selection.configured,choices:selection.choices??null,description:selection.description})
   row.providers=[[true,false],[false,false],[true,true]].map(([agentPreset,inheritsParentContext])=>{try{selection.assertProvider({name:'test',capabilities:{agentPreset},inheritsParentContext});return true}catch{return false}})
   row.value=selection.resolve(input.request)??null
  }
 }catch(error:any){row.error=error.message}
 rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
