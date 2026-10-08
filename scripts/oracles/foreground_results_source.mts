import {createHash} from 'node:crypto'
import {readFileSync,writeFileSync} from 'node:fs'
import {resolve,join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'

const options=Object.fromEntries(process.argv.slice(2).reduce((pairs:string[][],value,index,args)=>{
  if(value.startsWith('--'))pairs.push([value.slice(2),args[index+1]])
  return pairs
},[]))
const root=resolve(options.root),output=resolve(options.output)
const load=async(path:string)=>await import(pathToFileURL(join(root,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts')
const {LlmRuntime}=await load('packages/llm/llm/src/index.ts')
const {default:Sessions}=await load('packages/core/session/src/index.ts')
const {default:Tools}=await load('packages/core/tools/src/index.ts')
const {default:Prompt}=await load('packages/core/system-prompt/src/index.ts')
const {default:Agents}=await load('packages/core/agent/src/index.ts')
const {default:Loop}=await load('packages/core/agent-loop/src/index.ts')
const {default:Subagents}=await load('packages/subagent/subagent/src/index.ts')
const Tool=await load('packages/subagent/tool-subagent/src/index.ts')
const rows:any[]=[]
for(const reason of ['completed','aborted','error','max-tokens','refusal','provider-extra']){
  for(const diagnostic of [undefined,'','具体失败 🧪'])for(const partial of [false,true]){
    const name=reason+'/'+(diagnostic===undefined?'absent':diagnostic===''?'empty':'text')+'/'+partial
    const terminal={stopReason:reason,output:partial?[{type:'text',text:'部分答案 🧪'},{type:'text',text:'\nsecond line'}]:[],
      ...diagnostic===undefined?{}:{diagnostic}}
    const ctx=new Context(),trace={started:0,disposed:0}
    let handle:any
    try{
      for(const provider of [LlmRuntime,Sessions,Tools,Prompt,Agents])await ctx.plugin(provider)
      await ctx.plugin(Loop,{agents:[]})
      await ctx.plugin(Subagents)
      ctx.subagents.registerProvider({name:'foreground-probe',inheritsParentContext:false,capabilities:{depthLimit:true},
        async start(){trace.started++;return {id:'foreground-fixed-run',result:Promise.resolve(structuredClone(terminal)),
          async dispose(){trace.disposed++}}}} as any)
      handle=await ctx.agents.create({sessionId:'foreground-fixed-parent',
        setup:async(agentCtx:any)=>{await agentCtx.plugin(Tool,{provider:'foreground-probe',enableRunInBackground:false})}})
      const result=await ctx.tools.execute({name:'subagent',arguments:{description:'Actual failure consumer',prompt:'Controlled provider terminal result'},
        callId:'foreground-fixed-call',signal:new AbortController().signal,agent:handle.agent})
      rows.push({name,terminal,trace,result})
    }finally{if(handle)await handle.dispose();await ctx.fiber.dispose()}
  }
}
writeFileSync(output,JSON.stringify({sourceRoot:root,node:process.version,rows,
  observerSha256:createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex')},null,2)+'\n',{encoding:'utf8',flag:'wx'})
