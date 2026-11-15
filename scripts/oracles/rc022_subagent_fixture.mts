import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
export const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
export async function setup(workspace:string,directory?:string){
 const {Context}=await load('vendor/cordis/src/index.ts'),ctx=new Context()
 try{
  for(const path of ['packages/llm/llm/src/index.ts','packages/core/session/src/index.ts','packages/session/session-projection/src/index.ts','packages/core/system-prompt/src/index.ts','packages/core/tools/src/index.ts','packages/core/tool-executor-native/src/index.ts','packages/core/agent/src/index.ts']){const module=await load(path);await ctx.plugin(module.default??module)}
  const {default:Loop}=await load('packages/core/agent-loop/src/index.ts'),Backend=await load('packages/session/session-persistence-jsonl/src/index.ts'),{default:Subagents}=await load('packages/subagent/subagent/src/index.ts'),Spawn=await load('packages/subagent/subagent-spawn-in-process/src/index.ts'),{TestSessionQuery}=await load('packages/subagent/subagent/tests/test-session-query.ts'),{MockAdapter}=await load('packages/core/agent-loop/tests/mock-adapter.ts')
  class Hanging extends MockAdapter{
   override async *stream(options:any){
    yield {type:'block-start',index:0,blockType:'text'} as const;yield {type:'text-delta',index:0,text:'partial'} as const
    await new Promise((_resolve,reject)=>{if(options.signal.aborted)reject(Error('aborted'));else options.signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true})})
   }
  }
  await ctx.plugin(Backend,{root:workspace,compression:'none'});await ctx.plugin(Loop,{agents:[]});ctx.llm.registerAdapter(['script'],new Hanging([]));await ctx.plugin(TestSessionQuery)
  if(directory===undefined){ctx.provide('workingDirectory');ctx.workingDirectory={ensure:async()=> 'C:/rc022-work',set:async(_agent:any,path:string)=>path}}
  else{await ctx.plugin((await load('packages/fs/fs-local/src/index.ts')).default,{cwd:directory});await ctx.plugin((await load('packages/session/working-directory/src/index.ts')).default,{defaultDirectory:directory})}
  await ctx.plugin(Subagents);const provider=await ctx.plugin(Spawn)
  return {ctx,service:ctx.subagents,provider,signal:new AbortController().signal}
 }catch(error){await ctx.fiber.dispose();throw error}
}
