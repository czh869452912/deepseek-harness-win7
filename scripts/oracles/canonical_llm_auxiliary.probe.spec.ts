import {execFileSync} from 'node:child_process'
import {expect,it} from 'vitest'
import {writeFileSync} from 'node:fs'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{createUserMessage,LlmAdapter,LlmError} from '@deepseek-ai/dsh-llm'
import Sessions,{SessionId} from '@deepseek-ai/dsh-session'
import {summarizeWithLlm} from '../../reference/packages/compaction/compaction-basic/src/summarizer.ts'

it('records adapter cause normalization through actual auxiliary stream and summarizer',async()=>{
  const rows=[]
  for(const name of ['before-output','after-partial']){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    await ctx.plugin(Sessions)
    class Adapter extends LlmAdapter {
      async *stream(){
        if(name === 'after-partial'){
          yield {type:'block-start' as const,index:0,blockType:'text' as const}
          yield {type:'text-delta' as const,index:0,text:'discarded'}
        }
        throw new LlmError('provider failed','SERVER',{status:503,requestId:'fixture-request',cause:new Error('socket closed')})
      }
    }
    ctx.llm.registerAdapter(['failure-probe'],new Adapter())
    const session=ctx.sessions.create(SessionId('summary-session'))
    const message=createUserMessage({content:[{type:'text',text:'important facts'}],source:{kind:'user'}})
    const chunks=[]
    let error:any
    try{
      for await(const chunk of ctx.llm.stream({provider:'failure-probe',model:'probe',messages:[message]})) chunks.push(chunk)
      try{
        await summarizeWithLlm(ctx,{summarizationProvider:'failure-probe',summarizationModel:'probe',maxTokens:17},{messages:[message]},
          {session,options:{provider:'failure-probe',model:'probe'}} as any)
      }catch(caught:any){error={name:caught.name,message:caught.message,code:caught.code}}
      expect(chunks.at(-1)).toEqual({type:'finish',reason:{kind:'error',failure:{message:'provider failed',code:'SERVER',status:503,requestId:'fixture-request'}}})
      expect(error).toEqual({name:'Error',message:'provider failed',code:'SERVER'})
      rows.push({name,chunks,error})
    }finally{await ctx.fiber.dispose()}
  }
  writeFileSync(process.env.DSH_CANONICAL_LLM_AUXILIARY_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
