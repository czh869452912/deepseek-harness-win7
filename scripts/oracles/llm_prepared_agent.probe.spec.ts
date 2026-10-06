import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {expect,it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import {SessionId} from '@deepseek-ai/dsh-session'
import {LlmAdapter,createUserMessage,isAgentLoopRequest} from '@deepseek-ai/dsh-llm'
import {mountAgentLoopTestDependencies} from '@deepseek-ai/dsh-agent-loop-testkit'

it('captures actual AgentLoop public prepared request consumers',async()=>{
  const rows=[]
  for(const name of ['defaults','request-overrides','signal','registration-switch','missing-middleware']){
    const ctx=new Context()
    await mountAgentLoopTestDependencies(ctx)
    await ctx.plugin(AgentLoop,{agents:[]})
    const trace:any[]=[],requests:any[]=[]
    let agent:any
    let requestSignal:any
    let dispose:()=>void=()=>{}
    const snapshot=(options:any)=>({...options,signal:options.signal===undefined?{present:false}:{
      present:true,same:options.signal===requestSignal,aborted:options.signal.aborted,
      canThrow:typeof options.signal.throwIfAborted==='function'}})
    class Adapter extends LlmAdapter{
      constructor(private generation:string){super()}
      async prepareCall(provider:string,model:string,signal:any){
        trace.push({kind:'prepare',generation:this.generation,provider,model,signalPresent:signal!==undefined,
          signalSame:signal===requestSignal,aborted:signal?.aborted??null})
        if(name==='registration-switch'&&this.generation==='first'){
          dispose();ctx.llm.registerAdapter(['fixture'],new Adapter('second'))
        }
        return {model:{provider,id:model,name:model,context:{contextWindow:100},defaultMaxTokens:256,
          reasoning:{efforts:[{id:'low',name:'Low'},{id:'high',name:'High'}],defaultEffort:'low'}},
          stream:(options:any)=>this.dispatch(options)}
      }
      async *dispatch(options:any){requests.push({generation:this.generation,request:snapshot(options),
        frozen:Object.isFrozen(options),marked:isAgentLoopRequest(options)})
        yield {type:'finish' as const,reason:{kind:'stop' as const}}}
      async *stream(){throw new Error('unprepared adapter dispatch forbidden')}
    }
    if(name!=='missing-middleware')dispose=ctx.llm.registerAdapter(['fixture'],new Adapter('first'))
    ctx.on('agent/request',async(data,next)=>{
      requestSignal=data.signal
      const config=await next()
      return name==='request-overrides'?{...config,maxTokens:128,reasoningEffort:'low'}:config
    })
    ctx.on('llm/stream',(options,next)=>{
      trace.push({kind:'middleware',request:snapshot(options),frozen:Object.isFrozen(options),marked:isAgentLoopRequest(options)})
      if(name==='missing-middleware')return (async function*(){yield {type:'finish' as const,reason:{kind:'stop' as const}}})()
      return next()
    })
    agent=ctx.agentLoop.create(SessionId('prepared-agent'),{provider:'fixture',model:'model',
      ...name==='request-overrides'?{maxTokens:64,reasoningEffort:'high' as any}:{}})
    try{
      agent.followup(createUserMessage({content:[{type:'text',text:'prepared request'}],source:{kind:'user'}}))
      await agent.whenIdle()
      rows.push({name,trace,requests,events:agent.session.events.map(event=>({type:event.type,data:event.data})),messages:agent.session.deriveMessages()})
    }finally{await ctx.fiber.dispose()}
  }
  expect(rows).toHaveLength(5)
  writeFileSync(process.env.DSH_LLM_PREPARED_AGENT_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
