import {execFileSync} from 'node:child_process'
import {expect,it} from 'vitest'
import {writeFileSync} from 'node:fs'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter,LlmError,HarnessError} from '@deepseek-ai/dsh-llm'

function failure(name:string):unknown{
  if(name === 'primitive') return 'plain failure'
  if(name === 'empty-primitive') return ''
  if(name === 'null-primitive') return null
  if(name === 'hostile-primitive') return {[Symbol.toPrimitive](){throw new Error('coercion failed')}}
  if(name === 'harness') return new HarnessError('owned failure','OWNED')
  if(name === 'llm') return new LlmError('provider failed','SERVER',{status:503,providerRetryAfterMs:50,requestId:'fixture-request',cause:new Error('socket closed')})
  const error=new Error('provider failed') as any
  if(name === 'foreign-code') error.code='FOREIGN'
  if(name === 'foreign-valid') Object.assign(error,{code:'FOREIGN',failure:{message:'carried failure',code:'FOREIGN',status:429,providerRetryAfterMs:25,requestId:'foreign-request'}})
  if(name.startsWith('foreign-null-')) Object.assign(error,{code:'FOREIGN',failure:{message:'carried failure',code:'FOREIGN',[{'status':'status','retry':'providerRetryAfterMs','id':'requestId'}[name.slice(13)]!]:null}})
  if(name === 'foreign-mismatch') Object.assign(error,{code:'FOREIGN',failure:{message:'carried failure',code:'OTHER'}})
  if(name === 'foreign-empty-id') Object.assign(error,{code:'FOREIGN',failure:{message:'carried failure',code:'FOREIGN',requestId:''}})
  if(name === 'accessor-code'){
    error.failure={message:'carried failure',code:'FOREIGN'}
    Object.defineProperty(error,'code',{get(){throw new Error('code getter failed')}})
  }
  if(name === 'accessor-failure') Object.defineProperty(error,'failure',{get(){throw new Error('failure getter failed')}})
  if(name === 'accessor-message') Object.defineProperty(error,'message',{get(){throw new Error('message getter failed')}})
  return error
}

it('records actual final adapter failure boundary and middleware ownership',async()=>{
  const rows=[]
  const names=['plain','primitive','empty-primitive','null-primitive','hostile-primitive','harness','llm','foreign-code','foreign-valid','foreign-mismatch','foreign-empty-id','accessor-code','accessor-failure','accessor-message','foreign-null-status','foreign-null-retry','foreign-null-id']
  for(const name of names) for(const phase of ['dispatch','iterate','after-partial']){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const error=failure(name)
    class Adapter extends LlmAdapter{
      stream():AsyncIterable<any>{
        if(phase === 'dispatch') throw error
        return (async function*(){
          if(phase === 'after-partial') yield {type:'text-delta',index:0,text:'partial'}
          throw error
        })()
      }
    }
    ctx.llm.registerAdapter(['fixture'],new Adapter())
    const chunks=[]
    let thrown:any
    try{
      try{for await(const chunk of (await ctx.llm.prepareCall({provider:'fixture',model:'model'})).stream({provider:'fixture',model:'model',messages:[]})) chunks.push(chunk)}
      catch(caught:any){thrown={name:caught?.name,message:caught?.message}}
      expect(thrown).toBeUndefined()
      expect(chunks.at(-1)?.type).toBe('finish')
      rows.push({name:name+'/'+phase,chunks,...(thrown ? {error:thrown}:{})})
    }finally{await ctx.fiber.dispose()}
  }
  for(const name of ['middleware-before','middleware-after','consumer']){
    const ctx=new Context()
    await ctx.plugin(LlmRuntime)
    const closed:string[]=[]
    class Adapter extends LlmAdapter{
      async *stream(){try{yield {type:'text-delta' as const,index:0,text:'partial'};yield {type:'finish' as const,reason:{kind:'stop' as const}}}finally{closed.push('closed')}}
    }
    ctx.llm.registerAdapter(['fixture'],new Adapter())
    if(name.startsWith('middleware')) ctx.on('llm/stream',async function*(options,next){
      if(name === 'middleware-before') throw new Error('middleware failed')
      for await(const chunk of next()){yield chunk;throw new Error('middleware failed')}
    })
    const chunks=[]
    let error:any
    try{
      try{for await(const chunk of (await ctx.llm.prepareCall({provider:'fixture',model:'model'})).stream({provider:'fixture',model:'model',messages:[]})){chunks.push(chunk);if(name === 'consumer') throw new Error('consumer failed')}}
      catch(caught:any){error={name:caught.name,message:caught.message}}
      expect(error).toEqual({name:'Error',message:name === 'consumer' ? 'consumer failed':'middleware failed'})
      rows.push({name,chunks,error,closed})
    }finally{await ctx.fiber.dispose()}
  }
  writeFileSync(process.env.DSH_LLM_PREPARED_FAILURE_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
