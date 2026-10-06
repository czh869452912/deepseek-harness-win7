import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter} from '@deepseek-ai/dsh-llm'
import {expect,it} from 'vitest'

it('captures actual standalone config query ownership',async()=>{
  const rows=[]
  const names=['plain','defaults','override','custom-prepare','no-adapter','unsupported','null-with-default','null-without-reasoning','pending-replace','pending-input']
  for(const name of names){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const trace:any[]=[]
    const signal=new AbortController().signal
    let release:()=>void=()=>{},entered:()=>void=()=>{}
    const pending=new Promise<void>(resolve=>{release=resolve})
    const ready=new Promise<void>(resolve=>{entered=resolve})
    const defaults=['defaults','override','null-with-default'].includes(name)
    class Adapter extends LlmAdapter{
      constructor(readonly generation:string){super()}
      async resolveModel(provider:string,id:string,selectedSignal?:AbortSignal){
        trace.push({kind:'resolve',generation:this.generation,provider,id,signalSame:selectedSignal===signal})
        if(name.startsWith('pending-')){entered();await pending}
        return {provider,id,name:id,...defaults?{defaultMaxTokens:4096,reasoning:{efforts:[{id:'low',name:'Low'},{id:'high',name:'High'}],defaultEffort:'low'}}:{}}
      }
      async prepareCall(provider:string,id:string,selectedSignal?:AbortSignal){
        trace.push({kind:'prepare',generation:this.generation,provider,id,signalSame:selectedSignal===signal})
        return {model:{provider,id,name:id,defaultMaxTokens:7},stream:options=>this.stream(options)}
      }
      async *stream(options:any){trace.push({kind:'unexpected-stream'});yield {type:'finish' as const,reason:{kind:'stop' as const}}}
    }
    if(name!=='no-adapter')ctx.llm.registerAdapter(['fixture'],new Adapter('first'))
    const config:any={provider:'fixture',model:'model',stop:['done'],extra:{value:1}}
    if(name==='override'){config.maxTokens=128;config.reasoningEffort='high'}
    if(name==='unsupported')config.reasoningEffort='invalid'
    if(name.startsWith('null-'))config.reasoningEffort=null
    let observed:any
    try{
      const querying=ctx.llm.resolveCallConfig(config,signal)
      if(name.startsWith('pending-')){
        await ready
        if(name==='pending-replace')ctx.llm.registerAdapter(['fixture'],new Adapter('second'))
        else config.model='changed-model'
        release()
      }
      const result=await querying
      observed={result:structuredClone(result),same:result===config,sameStop:result.stop===config.stop,input:structuredClone(config)}
      result.model='result-write'
      observed.inputAfterResultChange=structuredClone(config)
    }catch(caught:any){observed={error:{name:caught.name,message:caught.message,code:caught.code},input:structuredClone(config)}}
    finally{release();await ctx.fiber.dispose()}
    rows.push({name,trace,observed})
  }
  expect(rows).toHaveLength(names.length)
  writeFileSync(process.env.DSH_LLM_CONFIG_QUERY_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
