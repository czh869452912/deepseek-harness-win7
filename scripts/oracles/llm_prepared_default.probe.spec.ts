import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter} from '@deepseek-ai/dsh-llm'
import {expect,it} from 'vitest'

it('captures the original default adapter method ownership',async()=>{
  const rows=[]
  for(const name of ['late-default-stream','pending-default-stream']){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const trace:any[]=[],chunks:any[]=[]
    let release:()=>void=()=>{},entered:()=>void=()=>{}
    const pending=new Promise<void>(resolve=>{release=resolve})
    const ready=new Promise<void>(resolve=>{entered=resolve})
    class Adapter extends LlmAdapter{
      async resolveModel(provider:string,id:string){
        trace.push({kind:'resolve'})
        if(name==='pending-default-stream'){entered();await pending}
        return {provider,id,name:id}
      }
      async *stream(options:any){trace.push({kind:'first'});yield {type:'finish' as const,reason:{kind:'stop' as const}}}
    }
    const adapter=new Adapter()
    ctx.llm.registerAdapter(['fixture'],adapter)
    ctx.on('llm/stream',(options,next)=>{trace.push({kind:'middleware'});return next()})
    try{
      const preparing=ctx.llm.prepareCall({provider:'fixture',model:'model'})
      if(name==='pending-default-stream')await ready
      const replace=()=>{adapter.stream=async function*(options:any){trace.push({kind:'second'});yield {type:'finish' as const,reason:{kind:'stop' as const}}}}
      if(name==='pending-default-stream'){replace();release()}
      const prepared=await preparing
      if(name==='late-default-stream')replace()
      for await(const chunk of prepared.stream({...prepared.config,messages:[]}))chunks.push(chunk)
      rows.push({name,config:prepared.config,trace,chunks})
    }finally{release();await ctx.fiber.dispose()}
  }
  expect(rows).toHaveLength(2)
  writeFileSync(process.env.DSH_LLM_PREPARED_DEFAULT_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
