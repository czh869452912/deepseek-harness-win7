import {load} from './rc022_subagent_fixture.mts'
import {pathToFileURL} from 'node:url'
import {writeFileSync} from 'node:fs'
export async function definitions(){
 const {Context}=await load('vendor/cordis/src/index.ts'),tool=await load('packages/fs/tool-fs/src/index.ts'),entries:Record<string,any>={}
 for(const confined of [false,true]){
  const ctx=new Context(),definitions:any[]=[],services:any={tools:{register:(definition:any)=>{definitions.push(definition);return ()=>{}}},fs:{sandboxMode:confined?'read-only':undefined},workingDirectory:{ensure:async()=> 'C:/work'},systemPrompt:{section:()=>{},getSectionOrder:()=>1340},...confined?{sandboxPolicy:{resolve:()=>({mode:'read-only'})}}:{}}
  for(const [name,value] of Object.entries(services)){ctx.provide(name);ctx[name]=value}
  try{await ctx.plugin(tool,{read:false,readImage:false,write:false,edit:false,applyPatch:true});const definition=definitions[0];entries[confined?'confined':'local']={name:definition.name,description:definition.description,parameters:definition.parameters,outputSchema:definition.output.schema}}
  finally{await ctx.fiber.dispose()}
 }
 return {source:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',package:'@deepseek-ai/dsh-tool-fs',definitions:entries}
}
if(import.meta.url===pathToFileURL(process.argv[1]!).href){const value=await definitions();if(process.argv[3])writeFileSync(process.argv[3],JSON.stringify(value,null,2)+'\n');else console.log(JSON.stringify(value))}
