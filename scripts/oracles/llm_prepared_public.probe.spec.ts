import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {it,expect} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter} from '@deepseek-ai/dsh-llm'

it('captures actual public prepared handle dispatch ownership',async()=>{
  const rows=[]
  const names=['plain','defaults','repeat','mismatch-provider','mismatch-model','mismatch-temperature','mismatch-maxTokens','mismatch-reasoningEffort','mismatch-stop','mismatch-then-valid','late-config','middleware-config','replace-registration','mutate-input','mutate-model']
  for(const name of names){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const trace=[],requests=[],chunks=[],errors=[]
    const model:any={provider:'fixture',id:'model',name:'Model',inputModalities:['text'],context:{contextWindow:100},defaultMaxTokens:256,reasoning:{efforts:[{id:'low',name:'Low'},{id:'high',name:'High'}],defaultEffort:'low'}}
    class Adapter extends LlmAdapter{
      constructor(private generation:string){super()}
      async prepareCall(provider:string,id:string){trace.push({kind:'prepare',generation:this.generation,provider,model:id});const captured=this.generation;return {model,stream:(options:any)=>this.dispatch(options,captured)}}
      async *dispatch(options:any,generation:string){trace.push({kind:'dispatch',generation});requests.push(options);yield {type:'finish' as const,reason:{kind:'stop' as const}}}
      async *stream(){throw new Error('unprepared dispatch forbidden')}
    }
    const dispose=ctx.llm.registerAdapter(['fixture'],new Adapter('first'))
    ctx.on('llm/stream',(options,next)=>{trace.push({kind:'middleware'});if(name==='middleware-config') options.model='foreign';return next()})
    const config:any={provider:'fixture',model:'model',temperature:0.5,stop:['END']}
    if(name!=='defaults') Object.assign(config,{maxTokens:128,reasoningEffort:'high'})
    try{
      const prepared=await ctx.llm.prepareCall(config)
      const observed={config:structuredClone(prepared.config),adapterDefaults:structuredClone(prepared.adapterDefaults),context:structuredClone(prepared.context),inputModalities:structuredClone(prepared.inputModalities),retryPolicy:structuredClone(prepared.retryPolicy),frozen:{handle:Object.isFrozen(prepared),config:Object.isFrozen(prepared.config),stop:Object.isFrozen(prepared.config.stop),defaults:Object.isFrozen(prepared.adapterDefaults),context:Object.isFrozen(prepared.context),modalities:Object.isFrozen(prepared.inputModalities)}}
      if(name==='replace-registration'){dispose();ctx.llm.registerAdapter(['fixture'],new Adapter('second'))}
      if(name==='mutate-input'){config.model='foreign';config.stop.push('LATE')}
      if(name==='mutate-model'){model.inputModalities.push('image');model.context.contextWindow=200;model.reasoning.efforts[0].name='Changed'}
      const options:any={...prepared.config,messages:[]}
      const mismatch=name.startsWith('mismatch-') && name!=='mismatch-then-valid' ? name.slice('mismatch-'.length):undefined
      if(mismatch) options[mismatch]=mismatch==='stop' ? ['OTHER']:mismatch==='temperature' ? 0.7:mismatch==='maxTokens' ? 129:'foreign'
      const drain=async(selected:any,late=false)=>{
        try{const stream=prepared.stream(selected);if(late) selected.model='foreign';for await(const chunk of stream) chunks.push(chunk)}
        catch(caught:any){errors.push({name:caught.name,message:caught.message,...caught.code===undefined ? {}:{code:caught.code}})}
      }
      if(name==='mismatch-then-valid') await drain({...options,model:'foreign'})
      await drain(options,name==='late-config')
      if(name==='repeat') await drain(options)
      rows.push({name,observed,trace,requests,chunks,errors,after:{config:prepared.config,context:prepared.context,inputModalities:prepared.inputModalities}})
    }finally{await ctx.fiber.dispose()}
  }
  expect(rows).toHaveLength(15)
  writeFileSync(process.env.DSH_LLM_PREPARED_PUBLIC_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
