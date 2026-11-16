import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {DSH_LAUNCH_ENVIRONMENT_KEY,createLaunchEnvironmentSnapshot}=await load('packages/util/launch-environment/src/index.ts')
const {default:Web}=await load('packages/web/web/src/index.ts')
const search=await load('packages/web/web-search-deepseek/src/index.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],original=globalThis.fetch
const answer={content:[{type:'text',citations:[{url:'https://page.test',cited_text:'first citation'}]},
 {type:'web_search_tool_result',content:[{type:'web_search_result',url:'https://page.test',title:'Page',page_age:'today'},
 {type:'web_search_result',url:'https://page.test',title:'duplicate'}]}]}
try{
 for(const [index,entry] of inputs.entries()){
  const ctx=new Context(),events:any[]=[],sent:any[]=[],changes:string[]=[],auth=entry.auth
  let live:any
  const environment:any={DEEPSEEK_BASE_URL:'https://chat-must-ignore.test',DEEPSEEK_SEARCH_BASE_URL:'https://environment.test/v1'}
  if(['key','both','account-error'].includes(auth))Object.assign(environment,{DEEPSEEK_API_KEY:'environment-key',OWN_KEY:'own-key'})
  ctx.provide(DSH_LAUNCH_ENVIRONMENT_KEY,createLaunchEnvironmentSnapshot([{source:'process',values:environment}]))
  ctx.provide('deepseekAccount',{resolveToken:async(endpoint:string)=>{
   events.push('account:'+endpoint);if(auth==='account-error')throw Error('account-read-failed')
   return ['account','both'].includes(auth)?'account-token':undefined}})
  if(['store','store-error'].includes(auth))ctx.provide('credentials',{
   resolve:async(ref:string)=>{events.push('resolve:'+ref);if(auth==='store-error')throw Error('store-failed');return{value:'stored-key'}},
   describe:async(ref:string)=>{events.push('describe:'+ref);if(auth==='store-error')throw Error('store-failed');return{configured:true}}})
  const session={requestContext:()=>({provider:entry.current}),append:(name:string,data:any)=>{events.push({name,data})}}
  ctx.provide('agents',{currentInitiator:()=>entry.current===null?undefined:{session}})
  ctx.on('web/providers-changed',()=>{changes.push('changed')})
  globalThis.fetch=async(endpoint:any,init:any)=>{
   const headers=new Headers(init.headers)
   sent.push({endpoint,key:headers.get('x-api-key'),authorization:headers.get('authorization'),token:headers.get('x-dsh-auth-token'),body:JSON.parse(init.body)})
   return new Response(JSON.stringify(answer))
  }
  try{
   await ctx.plugin(Web,{searchProvider:'deepseek-official'})
   const config:any=entry.config==='literal'?{apiKey:'literal-key'}:{}
   if(entry.config==='custom')Object.assign(config,{baseURL:'https://custom.test/path/',apiKeyEnv:'OWN_KEY'})
   const fork=ctx.plugin({...search,apply:(owner:any,config:any)=>{live=config;return search.apply(owner,config)}},config);await fork
   const run=async()=>{
    const ready=await ctx.web.searchReady(entry.ready??undefined),boundary=events.length
    let result
    try{result={value:await ctx.web.search({query:'fixture'})}}
    catch(error:any){result={code:error.code??null,message:error.message}}
    return{ready,readinessEvents:boundary,result}
   }
   const result=[await run()]
   if(entry.live){
    for(const [key,value]of Object.entries({apiKey:'updated-key',apiKeyEnv:'OWN_KEY',baseURL:'https://updated.test/v2',model:'updated-model',apiVersion:'updated-version',maxTokens:19,maxUses:2}))live[key][Symbol.for('cosmokit.volatile.write')](value)
    result.push(await run())
   }
   await fork.dispose()
   rows.push({index,result,sent,events,changes:changes.length,afterDispose:ctx.web.listProviders()})
  }finally{await ctx.fiber.dispose()}
 }
}finally{globalThis.fetch=original}
process.stdout.write(JSON.stringify(rows))
