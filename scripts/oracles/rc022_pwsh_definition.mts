import {load} from './rc022_subagent_fixture.mts'
import {pathToFileURL} from 'node:url'
export async function definitions(){
const {Context}=await load('vendor/cordis/src/index.ts'),tool=await load('packages/shell/tool-pwsh/src/index.ts'),entries:Record<string,any>={}
for(const confined of [false,true])for(const variant of ['foreground','background','promote']){
 const ctx=new Context(),definitions:any[]=[]
 const services:any={tools:{register:(definition:any)=>{definitions.push(definition);return ()=>{}}},shell:{sandboxMode:confined?'read-only':undefined},shellEnv:{collect:()=>({})},workingDirectory:{ensure:async()=> 'C:/work'},systemPrompt:{section:()=>{},getSectionOrder:()=>1010},...confined?{sandboxPolicy:{resolve:()=>({mode:'read-only'})}}:{},...variant==='foreground'?{}:{jobs:{}}}
 for(const [name,value] of Object.entries(services)){ctx.provide(name);ctx[name]=value}
 try{await ctx.plugin(tool,{promoteOnTimeout:variant==='promote'});const definition=definitions.at(-1);entries[(confined?'confined-':'local-')+variant]={name:definition.name,description:definition.description,parameters:definition.parameters,outputSchema:definition.output.schema}}
 finally{await ctx.fiber.dispose()}
}
return {source:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',package:'@deepseek-ai/dsh-tool-pwsh',definitions:entries}
}
if(import.meta.url===pathToFileURL(process.argv[1]!).href)console.log(JSON.stringify(await definitions()))
