import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {default:LlmRuntime,LlmError}=await load('packages/llm/llm/src/index.ts')
const Account=await load('packages/llm/llm-deepseek-account/src/index.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],original=globalThis.fetch
try{
 for(const [index,entry] of input.entries()){
  const ctx=new Context(),calls:any[]=[],listings:any[]=[],raw:any={baseURL:'https://api.deepseek.com'}
  if(entry.mode==='unknown-override')raw.modelOverrides={'not-listed':{name:'Unknown'}}
  if(entry.mode==='known-override')raw.modelOverrides={'deepseek-v4.1':{name:'Friendly',maxTokens:64}}
  const config=Account.Config(raw)
  if(entry.mode!=='missing-service')ctx.provide('deepseekAccount',{
   async resolveToken(endpoint:string){calls.push({resolve:endpoint});if(entry.mode==='resolve-fail')throw new Error('account offline');return entry.token??undefined},
   async rejectToken(token:string){calls.push({reject:token});if(entry.mode==='reject-fail')throw new Error('storage offline')}
  })
  globalThis.fetch=async(url:any,init:any)=>{
   listings.push({url:String(url),headers:{'x-dsh-auth-token':new Headers(init.headers).get('x-dsh-auth-token')}})
   if(entry.mode==='listing-fail')throw new Error('offline')
   return new Response(JSON.stringify({data:[{id:'deepseek-v4.1',api_capabilities:{anthropic_messages:{}}}]}))
  }
  let row:any,llm:any
  try{
   await ctx.plugin(LlmRuntime);await ctx.plugin({inject:['llm'],apply(child:any){Account.apply(child,config)}});llm=ctx.llm
   let discovered:any
   try{discovered={models:await llm.listModels('deepseek-account')}}catch(error:any){discovered={error:{message:error.message,code:error.code??null}}}
   let authResult:any
   try{
    const adapter=llm.adapters.get('deepseek-account').adapter,auth=await adapter.dependencies.resolveAuth(adapter.dependencies.options()),mapped:any[]=[]
    for(const [message,code,status] of [['quota','QUOTA',402],['expired','AUTH',401],['denied','AUTH',403],['busy','SERVER',503]]){
     const error=new LlmError(message,code,{status,providerRetryAfterMs:3,requestId:'request'}),result=await auth.onRequestError(error)
     mapped.push({failure:result.failure,same:result===error,causeSame:result.cause===error})
    }
    const error=new Error('other'),result=await auth.onRequestError(error);mapped.push({otherSame:result===error})
    authResult={headers:auth.headers,mapped}
   }catch(error:any){authResult={error:{message:error.message,code:error.code??null}}}
   const directory=llm.listConfigurableProviders().map((entry:any)=>Object.fromEntries(['provider','displayName','settingsNs','settingsPath','error'].filter(key=>Object.hasOwn(entry,key)).map(key=>[key,entry[key]])))
   row={index,discovered,auth:authResult,calls,listings,directory,providers:llm.listProviders()}
  }finally{await ctx.fiber.dispose()}
  row.afterDispose={providers:llm.listProviders(),directory:llm.listConfigurableProviders()};rows.push(row)
 }
}finally{globalThis.fetch=original}
process.stdout.write(JSON.stringify(rows))
