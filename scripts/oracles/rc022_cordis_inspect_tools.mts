import fs from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
const Tool=await load('packages/extensions/tool-cordis/src/index.ts'),definitions:any[]=[]
Tool.apply({tools:{register:(definition:any)=>definitions.push(definition)},cordisInspect:{}} as any)
if(process.argv[3]==='--definitions'){
 console.log(JSON.stringify(definitions.map(tool=>({name:tool.name,description:tool.description,parameters:tool.parameters,outputSchema:tool.output.schema}))))
}else{
 const {Context}=await load('vendor/cordis/src/index.ts'),Prompt=(await load('packages/core/system-prompt/src/index.ts')).default,Tools=(await load('packages/core/tools/src/index.ts')).default
 const input=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
 for(const entry of input){
  const ctx=new Context(),calls:any[]=[];ctx.provide('cordisInspect',{list:()=>[{id:'fixture',platform:'host',description:'fixture',methods:[]}],query:async(...args:any[])=>{calls.push([args[0],args[1],args[2],args[3]===undefined?'<undefined>':args[3],args[4].id,args[5]?.aborted??null]);if(entry.failure)throw Error('query failed');return {value:args[3]??null}}})
  try{
   await ctx.plugin(Prompt);await ctx.plugin(Tools);const fiber=await ctx.plugin(Tool),tool=ctx.tools.get(entry.name),signal=new AbortController().signal
   const row:any={name:tool.name,description:tool.description,parameters:tool.parameters,output:tool.output.schema,safe:tool.isConcurrencySafe(entry.args),presentation:tool.presentCall(entry.args),calls}
   try{const value=await tool.execute(entry.args,{agent:entry.agent?{id:'agent'}:undefined,signal});row.value=value;row.render=await tool.output.render(entry.args,value)}catch(error:any){row.error=error.name==='ToolArgsError'?'args':error.message}
   await fiber.dispose();row.removed=ctx.tools.get(entry.name)===undefined;rows.push(row)
  }finally{await ctx.fiber.dispose()}
 }
 console.log(JSON.stringify(rows))
}
