import type {Context} from '@deepseek-ai/cordis'
import {LlmAdapter} from '@deepseek-ai/dsh-llm'

export const name='web-journey-fixture'
export const inject=['llm','sessions']

export function apply(ctx:Context){
  const record=(globalThis as any).__webJourneyProbe
  ctx.on('session/event',(session,event)=>record.events.push({sessionId:session.id,event:structuredClone(event)}))
  class Adapter extends LlmAdapter{
    private calls=new Map<string,number>()
    async listModels(_provider:string){return [{id:'fixture',name:'Controlled local browser journey'}]}
    async resolveModel(provider:string,id:string){
      record.lookups.push({provider,id})
      return {provider,id,name:id,context:{contextWindow:128000},defaultMaxTokens:4096}
    }
    async *stream(options:any){
      const {signal,...request}=options
      record.requests.push({request:structuredClone(request),signalPresent:signal!==undefined,signalAborted:signal?.aborted??false})
      let text:string
      if(options.purpose==='session-title'){
        text='Controlled browser journey'
      }else{
        const user=options.messages.findLast((message:any)=>message.role==='user'&&message.content.some((block:any)=>
          block.type==='text'&&['WEB_TOOL','WEB_QUESTION','WEB_APPROVAL','WEB_CANCEL','WEB_CORDIS','WEB_REOPEN'].includes(block.text.trim())))
        if(!user)throw new Error('Controlled browser turn has no actual user scenario')
        const prompt=user.content.filter((block:any)=>block.type==='text').map((block:any)=>block.text).join('')
        const scenario=['WEB_TOOL','WEB_QUESTION','WEB_APPROVAL','WEB_CANCEL','WEB_CORDIS','WEB_REOPEN'].find(name=>prompt.includes(name))
        if(!scenario)throw new Error('Unexpected controlled browser prompt')
        const call=(this.calls.get(user.id)??0)+1
        this.calls.set(user.id,call)
        if(scenario==='WEB_CANCEL'){
          yield {type:'block-start' as const,index:0,blockType:'text' as const}
          yield {type:'text-delta' as const,index:0,text:'WEB_CANCEL_WAITING'}
          let release:()=>void
          const ready=new Promise<void>(resolve=>release=resolve)
          const aborted=()=>release()
          const trace={scenario,attached:1,detached:0,aborted:false}
          record.cancellation.push(trace)
          signal.addEventListener('abort',aborted,{once:true})
          try{
            if(!signal.aborted)await ready
            trace.aborted=signal.aborted
            signal.throwIfAborted()
            throw new Error('Cancellation fixture resumed without an abort')
          }finally{
            (trace as any).finallyAborted=signal.aborted
            signal.removeEventListener('abort',aborted)
            trace.detached=1
          }
          return
        }
        if(call===1||scenario==='WEB_APPROVAL'&&call===2){
          let tool:string,argumentsValue:any
          if(scenario==='WEB_QUESTION'){
            tool='ask_user_question'
            argumentsValue={questions:[{id:'browser-choice',question:'Choose a local test result.',options:[
              {label:'Proceed',description:'Continue the controlled journey.'},{label:'Reject',description:'Return a rejection.'}]}]}
          }else if(scenario==='WEB_CORDIS'){
            tool='cordis_inspect_self'
            argumentsValue={}
          }else{
            tool='pwsh'
            let command='Write-Output WEB_TOOL_ROUND_TRIP'
            if(scenario==='WEB_APPROVAL'){
              const escaped=record.approvalArtifact.replaceAll("'","''")
              command="Set-Content -LiteralPath '"+escaped+"' -Value WEB_APPROVAL_ROUND_TRIP; Get-Content -LiteralPath '"+escaped+"'"
            }
            argumentsValue={command,description:'Run the controlled local browser tool.'}
            if(scenario==='WEB_APPROVAL'&&call===2){
              argumentsValue.sandbox_permissions='danger-full-access'
              argumentsValue.justification='Allow this exact controlled write to the isolated test home.'
            }
          }
          const argumentsText=JSON.stringify(argumentsValue),id=scenario.toLowerCase()+'-call-'+call
          yield {type:'block-start' as const,index:0,blockType:'tool-call' as const}
          yield {type:'tool-call-delta' as const,index:0,id:id as any,name:tool,argumentsDelta:argumentsText}
          yield {type:'block-end' as const,index:0,block:{type:'tool-call' as const,id:id as any,name:tool,arguments:argumentsText}}
          yield {type:'finish' as const,reason:{kind:'tool-calls' as const}}
          return
        }
        const result=options.messages.findLast((message:any)=>message.content.some((block:any)=>block.type==='tool-result'))
        if(!result)throw new Error('Controlled browser follow-up has no actual tool result')
        text=scenario+'_FINAL '+result.content.filter((block:any)=>block.type==='tool-result').map((block:any)=>
          block.content.filter((part:any)=>part.type==='text').map((part:any)=>part.text).join('')).join('')
      }
      yield {type:'block-start' as const,index:0,blockType:'text' as const}
      yield {type:'text-delta' as const,index:0,text}
      yield {type:'block-end' as const,index:0,block:{type:'text' as const,text}}
      yield {type:'finish' as const,reason:{kind:'stop' as const}}
    }
  }
  ctx.llm.registerAdapter(['web-journey-fixture'],new Adapter())
}
