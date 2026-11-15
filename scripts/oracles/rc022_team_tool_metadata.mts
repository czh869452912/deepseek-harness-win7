import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const {apply}=await import(pathToFileURL(resolve(process.argv[2]!,'packages/team/tool-agent-team/src/index.ts')).href)
export const collect=()=>{
 const tools:any[]=[];let policy=''
 apply({agentTeams:{isEnabled:()=>true},systemPrompt:{getSectionOrder:()=>600,section:(section:any)=>{policy=section.text({agent:{}})}},tools:{register:(tool:any)=>tools.push({name:tool.name,description:tool.description,parameters:tool.parameters,outputSchema:tool.output.schema,concurrencySafe:tool.isConcurrencySafe!==undefined})}} as any)
 return {target_upstream:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',policy,tools}
}
if(process.argv[1]?.endsWith('rc022_team_tool_metadata.mts'))process.stdout.write(JSON.stringify(collect(),null,2)+'\n')
