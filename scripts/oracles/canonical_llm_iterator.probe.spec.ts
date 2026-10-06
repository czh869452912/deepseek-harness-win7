import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {expect,it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter} from '@deepseek-ai/dsh-llm'

it('observes actual final iterator completion failure and downstream retirement',async()=>{
  const rows=[]
  for(const name of ['reject','reject-cleanup-error','eof','eof-cleanup-error','close','close-cleanup-error','close-no-return']){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const closed:string[]=[],chunks:any[]=[]
    let nextCalls=0,error:any
    class Adapter extends LlmAdapter{
      stream(){return {[Symbol.asyncIterator](){const iterator:any={next:async()=>{
        nextCalls+=1
        if(name.startsWith('reject')) throw new Error('iterator failed')
        if(name.startsWith('eof')) return nextCalls===1 ? {done:false,value:{type:'finish',reason:{kind:'stop'}}}:{done:true,value:undefined}
        return {done:false,value:{type:'text-delta',index:0,text:'partial'}}
      }}
      if(name!=='close-no-return') iterator.return=async()=>{closed.push('closed');if(name.endsWith('cleanup-error')) throw new Error('cleanup failed');return {done:true,value:undefined}}
      return iterator}}}
    }
    ctx.llm.registerAdapter(['fixture'],new Adapter())
    try{
      try{for await(const chunk of ctx.llm.stream({provider:'fixture',model:'model',messages:[]})){chunks.push(chunk);if(name.startsWith('close')) break}}
      catch(caught:any){error={name:caught.name,message:caught.message}}
      expect(closed.length).toBe(name.startsWith('close') && name!=='close-no-return' ? 1:0)
      rows.push({name,nextCalls,chunks,closed,...error ? {error}:{}})
    }finally{await ctx.fiber.dispose()}
  }
  writeFileSync(process.env.DSH_CANONICAL_LLM_ITERATOR_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
