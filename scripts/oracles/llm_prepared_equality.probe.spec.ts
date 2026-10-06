import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {expect,it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter} from '@deepseek-ai/dsh-llm'

it('captures strict public prepared call scalar and omission equality',async()=>{
  const rows=[]
  const names=['tokens-number-bool','tokens-bool-number','temperature-number-bool','temperature-bool-number','stop-number-bool','stop-bool-number','tokens-absent-null','tokens-null-absent','temperature-absent-null','temperature-null-absent','reasoning-absent-null','same-numbers','same-stop-copy','ignored-extra']
  for(const name of names){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const requests:any[]=[],chunks:any[]=[],errors:any[]=[]
    class Adapter extends LlmAdapter{
      async *stream(options:any){requests.push(options);yield {type:'finish' as const,reason:{kind:'stop' as const}}}
    }
    ctx.llm.registerAdapter(['fixture'],new Adapter())
    const config:any={provider:'fixture',model:'model'}
    if(name==='tokens-number-bool'||name==='same-numbers')config.maxTokens=1
    if(name==='tokens-bool-number')config.maxTokens=true
    if(name==='temperature-number-bool'||name==='same-numbers')config.temperature=1
    if(name==='temperature-bool-number')config.temperature=true
    if(name==='stop-number-bool')config.stop=[1]
    if(name==='stop-bool-number')config.stop=[true]
    if(name==='tokens-null-absent')config.maxTokens=null
    if(name==='temperature-null-absent')config.temperature=null
    if(name==='same-stop-copy')config.stop=['END','']
    try{
      const prepared=await ctx.llm.prepareCall(config)
      const options:any={...prepared.config,messages:[]}
      if(name==='tokens-number-bool')options.maxTokens=true
      if(name==='tokens-bool-number')options.maxTokens=1
      if(name==='temperature-number-bool')options.temperature=true
      if(name==='temperature-bool-number')options.temperature=1
      if(name==='stop-number-bool')options.stop=[true]
      if(name==='stop-bool-number')options.stop=[1]
      if(name==='tokens-absent-null')options.maxTokens=null
      if(name==='tokens-null-absent')delete options.maxTokens
      if(name==='temperature-absent-null')options.temperature=null
      if(name==='temperature-null-absent')delete options.temperature
      if(name==='reasoning-absent-null')options.reasoningEffort=null
      if(name==='same-stop-copy')options.stop=[...options.stop]
      if(name==='ignored-extra')options.extra='retained'
      try{for await(const chunk of prepared.stream(options))chunks.push(chunk)}
      catch(caught:any){errors.push({name:caught.name,message:caught.message,...caught.code===undefined?{}:{code:caught.code}})}
      rows.push({name,config:prepared.config,adapterDefaults:prepared.adapterDefaults,options,requests,chunks,errors})
    }finally{await ctx.fiber.dispose()}
  }
  expect(rows).toHaveLength(14)
  writeFileSync(process.env.DSH_LLM_PREPARED_EQUALITY_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
