import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const WRITE=Symbol.for('cosmokit.volatile.write')
const {default:LlmRuntime}=await load('packages/llm/llm/src/index.ts')
const ApiKey=await load('packages/llm/llm-deepseek-api-key/src/index.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],original=globalThis.fetch
try{
 for(const [index,entry] of input.entries()){
  const ctx=new Context(),calls:any[]=[],listings:any[]=[];let key=entry.key
  const config=ApiKey.Config(['public','listing-fail'].includes(entry.mode)?{}:{models:[{id:'configured-model'}]})
  ctx.provide('credentials',{async resolve(ref:string){calls.push(ref);return key===null||ref==='OTHER_KEY'?undefined:{value:key}}})
  globalThis.fetch=async(url:any,init:any)=>{
   listings.push({url:String(url),headers:{'x-api-key':new Headers(init.headers).get('x-api-key')}})
   if(entry.mode==='listing-fail')throw new Error('offline')
   return new Response(JSON.stringify({data:[{id:'deepseek-v4.1',api_capabilities:{anthropic_messages:{}}}]}))
  }
  let row:any,llm:any
  try{
   await ctx.plugin(LlmRuntime)
   await ctx.plugin({inject:['llm'],apply(child:any){ApiKey.apply(child,config)}})
   llm=ctx.llm
   const discover=async()=>{try{return{models:await llm.listModels('deepseek-official')}}catch(error:any){return{error:{message:error.message,code:error.code??null}}}}
   const results=[await discover()]
   if(entry.mode==='reload-ref'){config.apiKeyEnv[WRITE]('OTHER_KEY');ctx.emit('loader/volatile-update');results.push(await discover())}
   if(entry.mode==='live-credential'){key=null;results.push(await discover())}
   const directory=llm.listConfigurableProviders().map((entry:any)=>Object.fromEntries(['provider','displayName','settingsNs','settingsPath'].map(key=>[key,entry[key]])))
   row={index,results,calls,listings,providers:llm.listProviders(),directory}
  }finally{await ctx.fiber.dispose()}
  row.afterDispose={providers:llm.listProviders(),directory:llm.listConfigurableProviders()}
  rows.push(row)
 }
}finally{globalThis.fetch=original}
process.stdout.write(JSON.stringify(rows))
