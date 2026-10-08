import type {Context} from '@deepseek-ai/cordis'
import {LlmAdapter} from '@deepseek-ai/dsh-llm'

export const name='route-execution-fixture'
export const inject=['llm','sessions']

export function apply(ctx:Context){
  const record=(globalThis as any).__routeExecutionProbe
  ctx.on('session/event',(session,event)=>record.events.push({sessionId:session.id,event:structuredClone(event)}))
  ctx.on('agent/created',({agent})=>record.created.push({id:agent.id,header:structuredClone(agent.session.header),options:structuredClone(agent.options)}))
  ctx.on('agent/disposed',({agent})=>record.disposed.push(agent.id))
  class Adapter extends LlmAdapter{
    private calls=new Map<string,number>()
    async listModels(provider:string){return ['parent','child'].map(id=>({provider,id,name:id}))}
    async resolveModel(provider:string,id:string){
      record.lookups.push({provider,id})
      return {provider,id,name:id,context:{contextWindow:128000},defaultMaxTokens:4096,
        reasoning:{efforts:[{id:'low',name:'Low'},{id:'high',name:'High'}],defaultEffort:provider==='route-beta'?'low':'high'}}
    }
    async *stream(options:any){
      const {signal,...request}=options
      record.requests.push({request:structuredClone(request),signalPresent:signal!==undefined,signalAborted:signal?.aborted??false})
      const scenarios=['WORKFLOW_MODEL','WORKFLOW_CANCEL','RALPH_ROUNDS']
      const user=options.messages.findLast((message:any)=>message.role==='user'&&message.content.some((block:any)=>
        block.type==='text'&&(scenarios.includes(block.text)||block.text.startsWith('CHILD_')||block.text.startsWith('You are one fresh worker'))))
      const prompt=user.content.filter((block:any)=>block.type==='text').map((block:any)=>block.text).join('')
      let text:string
      if(options.purpose==='session-title')text='Controlled route execution'
      else if(prompt.startsWith('You are one fresh worker')){
        const first=prompt.includes('Ralph round: 1 of ')
        const value={status:first?'continue':'complete',summary:'Controlled round report',evidence:['Verified local fixture'],
          nextSteps:first?['Continue local work']:[],blocker:''}
        const encoded=JSON.stringify(value),id=first?'ralph-report-one':'ralph-report-two'
        yield {type:'block-start' as const,index:0,blockType:'tool-call' as const}
        yield {type:'tool-call-delta' as const,index:0,id:id as any,name:'structured_output',argumentsDelta:encoded}
        yield {type:'block-end' as const,index:0,block:{type:'tool-call' as const,id:id as any,name:'structured_output',arguments:encoded}}
        yield {type:'finish' as const,reason:{kind:'tool-calls' as const}}
        return
      }
      else if(prompt.startsWith('CHILD_')){
        if(prompt==='CHILD_CANCEL'){
          let release:()=>void
          const ready=new Promise<void>(resolve=>release=resolve)
          const trace={sessionId:options.sessionId,attached:true,detached:false,aborted:false}
          record.cancellation.push(trace)
          record.childStarted()
          const aborted=()=>release()
          signal.addEventListener('abort',aborted,{once:true})
          try{
            if(!signal.aborted)await ready
            trace.aborted=signal.aborted
            signal.throwIfAborted()
            throw new Error('Child cancellation did not abort')
          }finally{signal.removeEventListener('abort',aborted);trace.detached=true}
          return
        }
        text='CHILD_RESULT '+options.provider+'/'+options.model
      }else{
        const call=(this.calls.get(user.id)??0)+1
        this.calls.set(user.id,call)
        if(call===1){
          const argumentsValue:any={description:'Controlled route child',prompt:'CHILD_'+prompt,run_in_background:false}
          let tool=prompt==='FORK_INHERIT'?'subagent_fork':'subagent'
          if(['SPAWN_CHANGE','SPAWN_EFFORT','CANCEL'].includes(prompt))Object.assign(argumentsValue,{provider:'route-beta',model:'child'})
          if(prompt==='SPAWN_EFFORT')argumentsValue.reasoning_effort='high'
          if(prompt==='DENIED_ROUTE')Object.assign(argumentsValue,{provider:'outside',model:'child'})
          if(prompt==='HALF_ROUTE')argumentsValue.model='child'
          if(['WORKFLOW_MODEL','WORKFLOW_CANCEL'].includes(prompt)){
            tool='workflow'
            const child=prompt==='WORKFLOW_CANCEL'?'CHILD_CANCEL':'CHILD_WORKFLOW_MODEL'
            const script='phase("Selected child"); const value = await agent('+JSON.stringify(child)+', {provider:"route-beta",model:"child",label:"selected-child",phase:"Selected child"}); return {child:value};'
            for(const name of Object.keys(argumentsValue))delete argumentsValue[name]
            Object.assign(argumentsValue,{meta:{name:'selected-child',description:'Controlled canonical engine child'},script,args:{}})
          }else if(prompt==='RALPH_ROUNDS'){
            tool='ralph'
            for(const name of Object.keys(argumentsValue))delete argumentsValue[name]
            Object.assign(argumentsValue,{objective:'Complete controlled local rounds',maxRounds:2})
          }
          const encoded=JSON.stringify(argumentsValue),id='route-call-'+prompt.toLowerCase()
          yield {type:'block-start' as const,index:0,blockType:'tool-call' as const}
          yield {type:'tool-call-delta' as const,index:0,id:id as any,name:tool,argumentsDelta:encoded}
          yield {type:'block-end' as const,index:0,block:{type:'tool-call' as const,id:id as any,name:tool,arguments:encoded}}
          yield {type:'finish' as const,reason:{kind:'tool-calls' as const}}
          return
        }
        text='PARENT_RESULT '+prompt
      }
      yield {type:'block-start' as const,index:0,blockType:'text' as const}
      yield {type:'text-delta' as const,index:0,text}
      yield {type:'block-end' as const,index:0,block:{type:'text' as const,text}}
      yield {type:'finish' as const,reason:{kind:'stop' as const}}
    }
  }
  ctx.llm.registerAdapter(['route-alpha','route-beta'],new Adapter())
}
