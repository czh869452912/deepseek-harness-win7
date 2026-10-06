import {execFileSync} from 'node:child_process'
import {readFileSync,writeFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {it,expect} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter} from '@deepseek-ai/dsh-llm'

it('captures actual public catalog exact model validation and detachment',async()=>{
  const fixtures=JSON.parse(readFileSync('scripts/oracles/llm-metadata-fixtures.json','utf8')).fixtures
  const rows=[]
  for(const fixture of fixtures){
    for(const operation of ['catalog','resolve']){
      const ctx=new Context()
      await ctx.plugin(LlmRuntime)
      const model=structuredClone(fixture.model),trace=[]
      class Adapter extends LlmAdapter{
        async listModels(provider:string){trace.push({kind:'catalog',provider});return [model]}
        async resolveModel(provider:string,id:string){trace.push({kind:'resolve',provider,model:id});return model}
        async *stream(){yield {type:'finish' as const,reason:{kind:'stop' as const}}}
      }
      ctx.llm.registerAdapter(['fixture'],new Adapter())
      try{
        let result,error
        try{result=operation==='catalog' ? await ctx.llm.listModels('fixture'):await ctx.llm.resolveModelInfo('fixture','model')}
        catch(caught:any){error={name:caught.name,message:caught.message,...caught.code===undefined ? {}:{code:caught.code}}}
        rows.push({name:fixture.name+'-'+operation,trace,...error ? {error}:{result}})
      }finally{await ctx.fiber.dispose()}
    }
  }
  for(const operation of ['catalog','resolve']){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const model:any={provider:'fixture',id:'model',name:'Model',inputModalities:['text'],context:{contextWindow:100},reasoning:{efforts:[{id:'low',name:'Low'}],defaultEffort:'low'}},trace=[]
    class Adapter extends LlmAdapter{
      async listModels(provider:string){trace.push({kind:'catalog',provider});return [model]}
      async resolveModel(provider:string,id:string){trace.push({kind:'resolve',provider,model:id});return model}
      async *stream(){yield {type:'finish' as const,reason:{kind:'stop' as const}}}
    }
    ctx.llm.registerAdapter(['fixture'],new Adapter())
    try{
      const result=operation==='catalog' ? await ctx.llm.listModels('fixture'):await ctx.llm.resolveModelInfo('fixture','model')
      const before=structuredClone(result)
      model.name='Changed';model.inputModalities.push('image');model.context.contextWindow=200;model.reasoning.efforts[0].name='Changed'
      rows.push({name:'detach-'+operation,trace,before,after:result,source:model})
    }finally{await ctx.fiber.dispose()}
  }
  expect(rows).toHaveLength(fixtures.length*2+2)
  const inputs=Object.fromEntries(['reference/packages/llm/llm/src/index.ts','reference/packages/llm/llm/src/error.ts','scripts/oracles/llm_metadata_catalog.probe.spec.ts','scripts/oracles/llm-metadata-fixtures.json'].map(path=>[path,createHash('sha256').update(readFileSync(path)).digest('hex')]))
  writeFileSync(process.env.DSH_LLM_METADATA_CATALOG_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,inputs,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
