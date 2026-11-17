import {load} from './rc022_subagent_fixture.mts'
import {pathToFileURL} from 'node:url'
export async function definition(){
 const {Context}=await load('vendor/cordis/src/index.ts'),tool=await load('packages/boot/plugin-market/src/tools.ts'),ctx=new Context(),rows:any[]=[]
 for(const [name,value] of Object.entries({tools:{register:(row:any)=>{rows.push(row);return ()=>{}}},pluginMarket:{}})){ctx.provide(name);ctx[name]=value}
 try{await ctx.plugin(tool);const d=rows[0];return {source:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',package:'@deepseek-ai/dsh-plugin-market/tools',definition:{name:d.name,description:d.description,parameters:d.parameters,outputSchema:d.output.schema}}}
 finally{await ctx.fiber.dispose()}
}
if(import.meta.url===pathToFileURL(process.argv[1]!).href)console.log(JSON.stringify(await definition()))
