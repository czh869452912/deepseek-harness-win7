import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {expect,it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter,resolveRetryPolicy,deepFreeze} from '@deepseek-ai/dsh-llm'

it('records original prepared generation and replay ownership',async()=>{
  const names=['missing-provider','default-adapter','pending-register','pending-dispose','pending-config','unconsumed-repeat','signal','foreign-replay','shared-replay','held-replay','new-current-owner']
  const rows=[]
  for(const name of names){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const trace:any[]=[],requests:any[]=[],chunks:any[]=[],errors:any[]=[]
    const controller=new AbortController()
    let release:()=>void=()=>{}
    let entered:()=>void=()=>{}
    const pending=new Promise<void>(resolve=>{release=resolve})
    const ready=new Promise<void>(resolve=>{entered=resolve})
    const config:any={provider:'fixture',model:'model',stop:['END']}
    const model:any={provider:'fixture',id:'model',name:'Model',inputModalities:['text'],context:{contextWindow:100},defaultMaxTokens:256}
    class BaseAdapter extends LlmAdapter{
      constructor(readonly generation:string){super()}
      providerRetryPolicy(){return resolveRetryPolicy({mode:'normal',maxRetries:this.generation==='first'?2:7})}
      async resolveModel(provider:string,identifier:string,signal?:AbortSignal){
        trace.push({kind:'resolve',generation:this.generation,provider,model:identifier,signalSame:signal===controller.signal})
        return model
      }
      async *stream(options:any){
        trace.push({kind:'dispatch',generation:this.generation})
        const {signal,...values}=options
        requests.push({values,signalSame:signal===controller.signal,frozen:Object.isFrozen(options),messagesFrozen:Object.isFrozen(options.messages)})
        yield {type:'finish' as const,reason:{kind:'stop' as const}}
      }
    }
    class Adapter extends BaseAdapter{
      async prepareCall(provider:string,identifier:string,signal?:AbortSignal){
        trace.push({kind:'prepare',generation:this.generation,provider,model:identifier,signalSame:signal===controller.signal})
        if(name.startsWith('pending-')){entered();await pending}
        return {model,stream:(options:any)=>this.stream(options)}
      }
    }
    const first=name==='default-adapter'?new BaseAdapter('first'):new Adapter('first')
    let dispose:()=>void=()=>{}
    if(name!=='missing-provider') dispose=ctx.llm.registerAdapter(name==='shared-replay'?['fixture','history']:['fixture'],first)
    if(name==='foreign-replay')ctx.llm.registerAdapter(['history'],new Adapter('second'))
    ctx.on('llm/stream',(options,next)=>{trace.push({kind:'middleware'});return next()})
    let observed:any
    try{
      const preparing=ctx.llm.prepareCall(config,controller.signal)
      if(name.startsWith('pending-')){
        await ready
        if(name==='pending-config')config.model='foreign'
        else{dispose();if(name==='pending-register')ctx.llm.registerAdapter(['fixture'],new Adapter('second'))}
        release()
      }
      const prepared=await preparing
      observed={config:prepared.config,retryPolicy:prepared.retryPolicy,adapterDefaults:prepared.adapterDefaults,context:prepared.context,inputModalities:prepared.inputModalities}
      if(name==='held-replay'||name==='new-current-owner'){dispose();ctx.llm.registerAdapter(['fixture'],name==='held-replay'?first:new Adapter('second'))}
      const history=name.includes('replay')||name==='new-current-owner'
      const options:any={...prepared.config,messages:history?[{id:'fixed-message',role:'assistant',content:[{type:'text',text:'earlier'}],source:{kind:'model',provider:name==='shared-replay'||name==='foreign-replay'?'history':'fixture',model:'old-model',replayState:{opaque:'state'}}}]:[],signal:controller.signal}
      if(history)deepFreeze(options)
      const stream=prepared.stream(options)
      if(name==='unconsumed-repeat'){
        try{prepared.stream(options)}catch(caught:any){errors.push({name:caught.name,message:caught.message,code:caught.code})}
      }
      for await(const chunk of stream)chunks.push(chunk)
      rows.push({name,observed,trace,requests,chunks,errors,signal:{frozen:Object.isFrozen(controller.signal),aborted:controller.signal.aborted}})
    }catch(caught:any){rows.push({name,...observed===undefined?{}:{observed},trace,requests,chunks,errors:[...errors,{name:caught.name,message:caught.message,...caught.code===undefined?{}:{code:caught.code}}],signal:{frozen:Object.isFrozen(controller.signal),aborted:controller.signal.aborted}})}
    finally{release();await ctx.fiber.dispose()}
  }
  expect(rows).toHaveLength(names.length)
  writeFileSync(process.env.DSH_LLM_PREPARED_GENERATION_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
