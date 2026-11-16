import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {DSH_LAUNCH_ENVIRONMENT_KEY,createLaunchEnvironmentSnapshot}=await load('packages/util/launch-environment/src/index.ts')
const {default:Web}=await load('packages/web/web/src/index.ts')
const api=await load('packages/web/web-deepseek-api/src/index.ts')
const {provideRoutes}=await load('packages/web/web-deepseek-api/tests/routes.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],original=globalThis.fetch
function routes(mode:string){
 const rows:any[]=mode==='none'?[]:[{provider:'deepseek-official',config:{baseURL:'https://key.test/anthropic/path',apiKeyEnv:'ROUTE_KEY'}},{provider:'deepseek-account',config:{baseURL:'https://account.test/anthropic/path'}}]
 if(mode==='invalid-key-route')rows[0].config.baseURL='not a url'
 if(mode==='invalid-account-route')rows[1].config.baseURL='not a url'
 if(mode==='inactive-account')rows[1].state=0
 if(mode==='foreign-account')rows[1].name='@fixture/other'
 if(mode==='nested-account')rows[1].settingsPath=['nested']
 return rows
}
try{
 for(const [index,entry] of inputs.entries()){
  const ctx=new Context(),events:string[]=[],sent:any[]=[],changes:string[]=[],capability=entry.capability,auth=entry.auth
  const environment:any=['key','both','account-error'].includes(auth)?{DEEPSEEK_API_KEY:'environment-key',ROUTE_KEY:'route-key',OWN_KEY:'own-key'}:{}
  if(auth==='invalid-key'){environment.DEEPSEEK_API_KEY='invalid\nkey';environment.ROUTE_KEY='invalid\nkey'}
  if('environment'in entry)environment.DEEPSEEK_BASE_URL=entry.environment
  ctx.provide(DSH_LAUNCH_ENVIRONMENT_KEY,createLaunchEnvironmentSnapshot([{source:'process',values:environment}]))
  ctx.provide('deepseekAccount',{resolveToken:async(endpoint:string)=>{events.push('account:'+endpoint);if(auth==='account-error')throw Error('account-read-failed');return ['account','both','account-error'].includes(auth)?'account-token':undefined},rejectToken:async(token:string)=>{events.push('reject:'+token)}})
  if(['store','store-error'].includes(auth))ctx.provide('credentials',{
   resolve:async(ref:string)=>{events.push('resolve:'+ref);if(auth==='store-error')throw Error('store-failed');return{value:'stored-key'}},
   describe:async(ref:string)=>{events.push('describe:'+ref);if(auth==='store-error')throw Error('store-failed');return{configured:true}}})
  provideRoutes(ctx,routes(entry.routes))
  const session={requestContext:()=>({provider:entry.provider}),deriveMessages:()=>[
   {role:'user',source:{kind:'user'},content:[{type:'text',text:'first question'}]},
   {role:'user',source:{kind:'injected'},content:[{type:'text',text:'must not send'}]}]}
  ctx.provide('agents',{currentInitiator:()=>entry.provider===null?undefined:{session}})
  ctx.on('web/providers-changed',()=>{changes.push('changed')})
  globalThis.fetch=async(endpoint:any,init:any)=>{
   const headers=new Headers(init.headers)
   sent.push({endpoint,authorization:headers.get('authorization'),token:headers.get('x-dsh-auth-token'),body:JSON.parse(init.body)})
   return new Response(JSON.stringify(capability==='search'?{results:[]}:{content:'# Page'}))
  }
  try{
   await ctx.plugin(Web,{searchProvider:'deepseek-search-api',fetchProvider:'deepseek-fetch-api'})
   const config:any={[capability+'Billing']:entry.billing,apiKey:'legacy-must-ignore',baseURL:'https://legacy.invalid'}
   if(entry.base!==undefined&&entry.base!==null)config[capability+'BaseURL']=entry.base
   if(entry.ref!==undefined&&entry.ref!==null)config[capability+'ApiKeyEnv']=entry.ref
   const fork=ctx.plugin(api,config);await fork
   const ready=await ctx.web[capability+'Ready'](entry.provider??undefined)
   let result
   try{result={value:await ctx.web[capability](capability==='search'?{query:'fixture'}:{url:'https://page.test'})}}
   catch(error:any){result={code:error.code??null,message:error.message}}
   await fork.dispose()
   rows.push({index,ready,result,sent,events,changes:changes.length,afterDispose:ctx.web.listProviders()})
  }finally{await ctx.fiber.dispose()}
 }
}finally{globalThis.fetch=original}
process.stdout.write(JSON.stringify(rows))
