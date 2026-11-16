import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context,Service}=await load('vendor/cordis/src/index.ts')
const {default:Authorization}=await load('packages/credentials/authorization/src/index.ts')
const {DeepSeekAccount}=await load('packages/credentials/deepseek-account/src/index.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],key='deepseek-account-platform/default',deviceKey='deepseek-account-platform/device'
const original=globalThis.fetch,log=console.error
try{
 for(const mode of input){
  const ctx=new Context(),records:any={},hits:any[]=[],diagnostics:any[]=[],events:any[]=[]
  const issuer=mode==='private'?'https://private.example':'https://platform.deepseek.com'
  let record:any={kind:'grant',payload:{version:1,token:mode==='mock-token'?'dsh_mock_fixture':'fixture-token',issuer}}
  if(mode==='foreign')record.payload.issuer='https://other.example'
  else if(mode==='invalid-record')record={kind:'api-key',apiKey:'secret'}
  else if(mode==='invalid-payload')record.payload=null
  else if(mode==='invalid-version')record.payload.version=true
  else if(mode==='invalid-token')record.payload.token=''
  else if(mode==='invalid-issuer')record.payload.issuer='bad-url'
  if(mode!=='signed-out')records[key]=record
  records[deviceKey]={kind:'grant',payload:{id:'12345678-1234-4234-8234-123456789abc'}}
  ctx.provide('credentials',{
   async readRecord(key:string){return records[key]===undefined?undefined:structuredClone(records[key])},
   async deleteRecord(key:string){if(key in records){delete records[key];ctx.emit('credentials/record-updated',key)}},
   async modifyRecord(key:string,mutate:any){const value=await mutate(records[key]);if(value!==undefined){records[key]=value;ctx.emit('credentials/record-updated',key)}return records[key]},
   async describeRecord(key:string){return{configured:key in records}}
  })
  await ctx.plugin(Authorization)
  for(const event of ['deepseek-account/session-expired','deepseek-account/signed-out'])ctx.on(event,()=>{events.push(event)})
  let stage='profile',currentUser='user-1'
  globalThis.fetch=async(url:any,init:any)=>{
   hits.push({url,method:init.method,headers:Object.fromEntries(new Headers(init.headers)),body:init.body??null})
   const path=new URL(url).pathname
   let payload:any={id:currentUser,email:'masked',id_profile:{name:'Name',picture:'url'}}
   if(path.endsWith('/get_user_summary'))payload={normal_wallets:[{currency:'CNY',balance:'0E-16'}],bonus_wallets:[]}
   else if(path.endsWith('/notifications/list'))payload={next_poll_after:600,notifications:[]}
   else if(path.endsWith('/logout'))payload=null
   let status=mode==='expired-http'&&stage==='profile'?401:200,envelope:any={code:0,data:{biz_code:0,biz_data:payload}}
   if(mode==='expired-code'&&stage==='profile')envelope={code:40003}
   if(mode==='profile-failed'&&stage==='refresh'||mode==='balance-failed'&&path.endsWith('/get_user_summary')||mode==='notification-failed'&&path.endsWith('/notifications/list'))status=503
   return new Response(JSON.stringify(envelope),{status})
  }
  console.error=(label:any,value:any)=>diagnostics.push({label:String(label).replace('[deepseek-account] ',''),...value})
  let result:any
  try{
   const config:any={requestHeaders:{Cookie:'a=1; keep=base','x-deployment':'base'},accountRequestHeaders:{cookie:'a=2; extra=override','x-account':'account'},embeddedPageDist:'desktop-dist'}
   if(mode==='private'){config.platformOrigin=issuer;config.inferenceOrigin='https://inference.example'}
   const account=new DeepSeekAccount(ctx,config);await account[Service.init]()
   const initial=await account.getState(),destinations=['https://api.deepseek.com/anthropic/v1/messages','https://inference.example/v1/files','https://api.deepseek.com:443/files?x=1','https://user@api.deepseek.com/files','https://other.example']
   const tokens=[];for(const url of destinations)tokens.push(await account.resolveToken(url)??null)
   const client={version:'fixture/1',locale:'zh_TW',timezoneOffsetSeconds:28800},changes:any[]=[]
   ;(account as any).listeners.add((kind:any)=>changes.push(kind))
   const profile=await account.getProfile(client),session=await account.getPlatformSession()
   stage='refresh';const refresh=await account.getProfile(client)
   currentUser='user-2';stage='identity';const identity=await account.getProfile(client),balance=await account.getBalance(client)
   let batch:any;try{batch={value:await account.getNotifications(client)}}catch(error:any){batch={error:{message:error.message,code:error.code??null}}}
   const device=await account.getDeviceIdentity()
   if(['reject-old','reject-current'].includes(mode))await account.rejectToken(mode==='reject-old'?'old-token':'fixture-token')
   if(mode==='sign-out')await account.signOut(client)
   result={initial,tokens,profile,session,refresh,identity,balance,batch,device,final:await account.getState(),changes,running:account.hasRunningAccountTasks()}
  }catch(error:any){result={error:{message:error.message,code:error.code??null}}}
  finally{await ctx.fiber.dispose()}
  rows.push({mode,result,records,hits,diagnostics,events})
 }
}finally{globalThis.fetch=original;console.error=log}
process.stdout.write(JSON.stringify(rows))
