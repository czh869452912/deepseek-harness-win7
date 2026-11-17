import {load} from './rc022_subagent_fixture.mts'
import {pathToFileURL} from 'node:url'
export async function definitions(seconds=60){
 const {Context}=await load('vendor/cordis/src/index.ts'),tool=await load('packages/schedule/tool-schedule/src/index.ts'),ctx=new Context(),rows:any[]=[],sections:any[]=[]
 for(const [name,value] of Object.entries({tools:{register:(definition:any)=>{rows.push(definition);return ()=>{}},get:()=>({})},systemPrompt:{section:(section:any)=>sections.push(section),getSectionOrder:()=>77},schedule:{deliveryLimits:()=>({newSessionIntervalSeconds:seconds})}})){ctx.provide(name);ctx[name]=value}
 try{await ctx.plugin(tool);return {source:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',package:'@deepseek-ai/dsh-tool-schedule',guidance:sections[0].text({scope:undefined}),definitions:rows.map(d=>({name:d.name,description:d.description,parameters:d.parameters,outputSchema:d.output.schema}))}}
 finally{await ctx.fiber.dispose()}
}
if(import.meta.url===pathToFileURL(process.argv[1]!).href)console.log(JSON.stringify(await definitions()))
