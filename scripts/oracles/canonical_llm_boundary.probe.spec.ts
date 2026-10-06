import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {expect,it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter} from '@deepseek-ai/dsh-llm'

it('captures actual original final selection preparation configuration and projection boundaries',async()=>{
  const rows=[]
  for(const name of ['unknown','prepare-error','prepare-invalid-model','default-config','invalid-max','invalid-reasoning','route-before-prepare','projection-unknown','projection-text']){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const trace:any[]=[],requests:any[]=[],chunks:any[]=[]
    class Adapter extends LlmAdapter{
      async prepareCall(provider:string,model:string,signal?:AbortSignal){
        trace.push({kind:'prepare',provider,model})
        if(name === 'prepare-error') throw new Error('preparation failed')
        const info:any={provider:name === 'prepare-invalid-model' ? 'foreign':provider,id:model,name:model}
        if(['default-config','invalid-max','invalid-reasoning','route-before-prepare'].includes(name)) Object.assign(info,{defaultMaxTokens:256,reasoning:{efforts:[{id:'low',name:'Low'},{id:'high',name:'High'}],defaultEffort:'low'}})
        if(name === 'projection-text') info.inputModalities=['text']
        return {model:info,stream:this.stream.bind(this)}
      }
      async *stream(options:any){trace.push({kind:'dispatch',provider:options.provider,model:options.model});requests.push(options);yield {type:'finish' as const,reason:{kind:'stop' as const}}}
    }
    if(name !== 'unknown') ctx.llm.registerAdapter(['fixture'],new Adapter())
    ctx.on('llm/stream',(options,next)=>{
      trace.push({kind:'middleware',provider:options.provider,model:options.model,messages:structuredClone(options.messages)})
      if(name === 'route-before-prepare') options.provider='fixture'
      return next()
    })
    const options:any={provider:name === 'unknown' ? 'missing':name === 'route-before-prepare' ? 'initial':'fixture',model:'model',messages:[]}
    if(name === 'invalid-max') options.maxTokens=0
    if(name === 'invalid-reasoning') options.reasoningEffort='unsupported'
    if(name.startsWith('projection')) options.messages=[{id:'image-message',role:'user',content:[{type:'image',attachment:{attachmentId:'sha256:'+'a'.repeat(64),mediaType:'image/png',bytes:3,width:1,height:1}}],source:{kind:'user'}}]
    let error:any
    try{
      try{for await(const chunk of ctx.llm.stream(options)) chunks.push(chunk)}catch(caught:any){error={name:caught.name,message:caught.message,...caught.code ? {code:caught.code}:{}}}
      expect(error).toBeUndefined()
      expect(chunks.at(-1)?.type).toBe('finish')
      rows.push({name,trace,requests,chunks,...error ? {error}:{}})
    }finally{await ctx.fiber.dispose()}
  }
  writeFileSync(process.env.DSH_CANONICAL_LLM_BOUNDARY_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
