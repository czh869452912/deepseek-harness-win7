/** Fixed Source metadata only; behavioral probes use actual runtime services. */
import {load} from './rc022_subagent_fixture.mts'
const Tool=await load('packages/subagent/tool-subagent/src/index.ts')
export async function collect(inheritsParentContext=false){
 const tools:any[]=[],sections:any[]=[],provider={name:'fixture',inheritsParentContext,prepareContinuable:()=>{},capabilities:{agentOptions:true,agentPreset:true,depthLimit:true}}
 const ctx:any={
  sessionProjections:{register:async()=>({})},subagents:{getProvider:()=>provider,resolveMaxDepth:()=>undefined},
  tools:{register:(tool:any)=>{tools.push(tool);return()=>{}},get:(name:string)=>tools.find(t=>t.name===name)},
  systemPrompt:{section:(section:any)=>sections.push(section),context:()=>{},getSectionOrder:()=>0,getContextOrder:()=>0},
  effect:(setup:any)=>setup(),on:()=>{},get:()=>undefined,
 }
 await Tool.apply(ctx,{provider:'fixture',maxDepth:'provider-managed'})
 const tool=tools[0]
 return {name:tool.name,description:tool.description,parameters:tool.parameters,outputSchema:tool.output.schema,guidance:sections[0].text({})}
}
if(process.argv[1]?.endsWith('rc022_delegation_metadata.mts'))process.stdout.write(JSON.stringify({fresh:await collect(),inherited:await collect(true)},null,2)+'\n')
