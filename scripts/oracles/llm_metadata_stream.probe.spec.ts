import {execFileSync} from 'node:child_process'
import {readFileSync,writeFileSync} from 'node:fs'
import {it,expect} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter} from '@deepseek-ai/dsh-llm'

it('captures actual metadata validation at final public streaming boundary',async()=>{
  const fixtures=JSON.parse(readFileSync('scripts/oracles/llm-metadata-fixtures.json','utf8')).fixtures
  const rows=[]
  for(const fixture of fixtures){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const model=structuredClone(fixture.model),trace=[],requests=[],chunks=[]
    class Adapter extends LlmAdapter{
      async prepareCall(provider:string,id:string){trace.push({kind:'prepare',provider,model:id});return {model,stream:this.stream.bind(this)}}
      async *stream(options:any){trace.push({kind:'dispatch'});requests.push(options);yield {type:'finish' as const,reason:{kind:'stop' as const}}}
    }
    ctx.llm.registerAdapter(['fixture'],new Adapter())
    ctx.on('llm/stream',(options,next)=>{trace.push({kind:'middleware'});return next()})
    try{
      for await(const chunk of ctx.llm.stream({provider:'fixture',model:'model',messages:[]})) chunks.push(chunk)
      rows.push({name:fixture.name,trace,requests,chunks})
    }finally{await ctx.fiber.dispose()}
  }
  expect(rows).toHaveLength(45)
  writeFileSync(process.env.DSH_LLM_METADATA_STREAM_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
