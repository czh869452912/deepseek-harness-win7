import {Context} from '@deepseek-ai/cordis'
import {LlmAdapter,LlmRuntime,ToolCallId} from '@deepseek-ai/dsh-llm'
import Sessions,{SessionId} from '@deepseek-ai/dsh-session'
import Agents from '@deepseek-ai/dsh-agent'
import Loop from '@deepseek-ai/dsh-agent-loop'
import Tools from '@deepseek-ai/dsh-tools'
import Prompt from '@deepseek-ai/dsh-system-prompt'
import Subagents from '@deepseek-ai/dsh-subagent'
import Settings from '../../reference/packages/subagent/tool-subagent/src/model-selection-settings.ts'
import * as Tool from '../../reference/packages/subagent/tool-subagent/src/index.ts'
import {readFileSync,writeFileSync} from 'node:fs'
import {execFileSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {resolve} from 'node:path'

Date.now=()=>1791244800000
const rows:any[]=[]
const calls=[{}, {provider:'alpha'}, {provider:'alpha',model:'fast'}, {provider:'alpha',model:'plain'},
  {provider:'alpha',model:'unlisted'}, {provider:'missing',model:'hidden'}, {provider:'beta'},
  {model:'fast'}, {provider:''}, {provider:'alpha',model:''}, {provider:'alpha',model:'outside'}]
class Adapter extends LlmAdapter{
  override providerInfo(provider:string){return {id:provider,name:provider.toUpperCase()+' API'}}
  override async listModels(provider:string){return [{provider,id:'fast',name:'Fast',description:'Focused work.'},{provider,id:'plain',name:'Plain'}]}
  override async resolveModel(provider:string,model:string){return {provider,id:model,name:model==='plain'?'Plain':'Fast',
    ...model==='plain'?{}:{description:'Focused work.',reasoning:{efforts:[{id:'low',name:'Low'},{id:'high',name:'High',description:'Quality first.'}],defaultEffort:'high'}}}}
  override stream(){throw new Error('model discovery observer must not stream')}
}
for(const enabled of [false,true])for(const inherits of [false,true])for(const defaults of [false,true])for(const mode of ['one-shot','continuable']){
  const name=[enabled,inherits,defaults,mode].join('/')
  const ctx=new Context()
  let handle:any
  try{
    for(const provider of [LlmRuntime,Sessions,Tools,Prompt,Agents])await ctx.plugin(provider)
    await ctx.plugin(Loop,{agents:[]})
    await ctx.plugin(Subagents)
    await ctx.plugin(Settings,{enabled,allowedModels:[{provider:'alpha',model:'fast'},{provider:'alpha',model:'plain'},{provider:'alpha',model:'unlisted'},{provider:'missing',model:'hidden'}]})
    ctx.llm.registerAdapter(['alpha'],new Adapter())
    ctx.subagents.registerProvider({name:'probe',inheritsParentContext:inherits,
      capabilities:{agentOptions:true,depthLimit:true,outputSchema:true,toolFilter:true,persona:true},
      ...defaults?{agentRouteDefaults:{provider:'alpha',model:'fast'}}:{},
      async start(){throw new Error('schema observer must not start a child')},
      async prepareContinuable(){throw new Error('schema observer must not prepare a child')},
    } as any)
    handle=await ctx.agents.create({sessionId:SessionId('model-probe-'+name),agentOptions:{provider:'alpha',model:'fast'},
      setup:async agentCtx=>{await agentCtx.plugin(Tool,{provider:'probe',modelSelectionSettings:true,backgroundMode:mode})}})
    rows.push({name:name+'/schema',schemas:ctx.tools.schemas(handle.agent),events:handle.agent.session.events})
    if(enabled){
      for(const [position,args] of calls.entries()){
        const result=await ctx.tools.execute({name:'list_subagent_models',arguments:args,callId:ToolCallId('model-call-'+position),signal:new AbortController().signal,agent:handle.agent})
        rows.push({name:name+'/call/'+position,result})
      }
    }
  }finally{if(handle)await handle.dispose();await ctx.fiber.dispose()}
}
const root=fileURLToPath(new URL('../../',import.meta.url))
writeFileSync(process.env.DSH_SUBAGENT_MODEL_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',resolve(root,'reference'),'rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,fixtureSha256:createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex'),rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
