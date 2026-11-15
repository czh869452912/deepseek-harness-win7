import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const {apply}=await import(pathToFileURL(resolve(process.argv[2]!,'packages/subagent/tool-subagent-control/src/index.ts')).href)
export const collect=()=>{
 const tools:any[]=[]
 apply({effect:()=>()=>{},systemPrompt:{getContextOrder:()=>0,context:()=>{}},tools:{register:(tool:any)=>tools.push({name:tool.name,description:tool.description,parameters:tool.parameters,outputSchema:tool.output.schema,concurrencySafe:tool.isConcurrencySafe!==undefined})}} as any)
 return {target_upstream:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',tools}
}
if(process.argv[1]?.endsWith('rc022_control_tool_metadata.mts'))process.stdout.write(JSON.stringify(collect(),null,2)+'\n')
