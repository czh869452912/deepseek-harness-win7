import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {Context} from '@deepseek-ai/cordis'
import LlmRuntime,{LlmAdapter} from '@deepseek-ai/dsh-llm'
import {expect,it} from 'vitest'

it('captures nullable and strictly typed call controls',async()=>{
  const rows=[]
  const names=['absent-default','null-default','null-no-default','null-no-reasoning','bool-default','number-default','null-max','explicit-zero']
  for(const method of ['resolveCallConfig','prepareCall'] as const){
    for(const name of names){
      const ctx=new Context()
      await ctx.plugin(LlmRuntime)
      const trace:any[]=[]
      const signal=new AbortController().signal
      class Adapter extends LlmAdapter{
        async resolveModel(provider:string,id:string,selectedSignal?:AbortSignal){
          trace.push({kind:'resolve',provider,id,signalSame:selectedSignal===signal})
          return {provider,id,name:id,defaultMaxTokens:4096,...name==='null-no-reasoning'?{}:{reasoning:{efforts:[{id:'low',name:'Low'}],...name==='null-no-default'?{}:{defaultEffort:'low'}}}}
        }
        async *stream(options:any){yield {type:'finish' as const,reason:{kind:'stop' as const}}}
      }
      ctx.llm.registerAdapter(['fixture'],new Adapter())
      const config:any={provider:'fixture',model:'model',stop:['done']}
      if(name.startsWith('null-')&&name!=='null-max')config.reasoningEffort=null
      if(name==='bool-default')config.reasoningEffort=true
      if(name==='number-default')config.reasoningEffort=1
      if(name==='null-max')config.maxTokens=null
      if(name==='explicit-zero')config.maxTokens=0
      let observed:any
      try{
        const result=await ctx.llm[method](config,signal)
        if(method==='prepareCall'){
          const {stream,...state}=result as any
          observed={result:state,input:structuredClone(config),sameConfig:state.config===config,sameStop:state.config.stop===config.stop}
        }else{
          observed={result,input:structuredClone(config),sameConfig:result===config,sameStop:(result as any).stop===config.stop}
        }
      }catch(caught:any){observed={error:{name:caught.name,message:caught.message,code:caught.code},input:structuredClone(config)}}
      finally{await ctx.fiber.dispose()}
      rows.push({name:method+'/'+name,trace,observed})
    }
  }
  expect(rows).toHaveLength(16)
  writeFileSync(process.env.DSH_LLM_CONFIG_NULLABLE_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
