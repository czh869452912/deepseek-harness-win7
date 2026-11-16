import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const api=await load('packages/llm/llm-deepseek-api-key/src/config.ts')
const account=await load('packages/llm/llm-deepseek-account/src/config.ts')
const credentials=await load('packages/llm/llm-deepseek/src/credential.ts')
const {DSH_LAUNCH_ENVIRONMENT_KEY}=await load('packages/util/launch-environment/src/index.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [kind,callback] of [['apiKey',api.resolveAdapterOptions],['account',account.resolveAccountOptions]] as const){
 for(const [index,config] of input.configs.entries()){
  let result:any
  try{result={value:callback(config)}}catch(error:any){result={error:error.message,code:error.code??null}}
  rows.push({kind,index,...result})
 }
}
for(const [name,module,plain] of [['apiKey',api,api.plainOptions],['account',account,account.plainAccountOptions]] as const){
 let result:any
 try{result={value:plain(module.Config({}))}}catch(error:any){result={error:error.message,code:error.code??null}}
 rows.push({kind:'parsed-defaults',name,...result})
}
for(const [index,inputCase] of input.credentials.entries()){
 const calls:any[]=[],services:any={
  [DSH_LAUNCH_ENVIRONMENT_KEY]:{get:()=>inputCase.ambient===null?undefined:{value:inputCase.ambient}},
 }
 if(inputCase.service!=='missing')services.credentials={
  resolve:async(ref:string)=>{
   calls.push(['resolve',ref]);if(inputCase.service==='failure')throw new Error('store offline')
   const value=({valid:'  stored  ',blank:'  ',invisible:'\ufeff',invalid:'bad\u0085key',custom:inputCase.raw} as any)[inputCase.service]
   return inputCase.service==='absent'?undefined:{value}
  },
  describe:async(ref:string)=>{
   calls.push(['describe',ref]);if(inputCase.service==='failure')throw new Error('store offline')
   return {configured:inputCase.service!=='absent'}
  },
 }
 const ctx={get:(key:string)=>services[key]},outcome:any={}
 for(const [name,callback] of [['value',credentials.resolveDeepSeekApiKey],['configured',credentials.deepSeekApiKeyConfigured]] as const){
  try{outcome[name]=(await callback(ctx,'TEST_KEY'))??null}catch(error:any){outcome[name]={error:error.message,code:error.code??null}}
 }
 rows.push({kind:'credentials',index,calls,...outcome})
}
for(const mode of ['missing','valid','denied','resolve-error','reject-error']){
 const calls:any[]=[],services:any={}
 if(mode!=='missing')services.deepseekAccount={
  resolveToken:async(endpoint:string)=>{calls.push(['resolve',endpoint]);if(mode==='resolve-error')throw new Error('account store offline');return mode==='denied'?undefined:'account-token'},
  rejectToken:async(token:string)=>{calls.push(['reject',token]);if(mode==='reject-error')throw new Error('remove failed')},
 }
 const ctx={get:(key:string)=>services[key]};let result:any
 try{result={value:(await credentials.resolveDeepSeekAccountToken(ctx,'https://endpoint.example/messages'))??null}}
 catch(error:any){result={error:error.message}}
 await credentials.rejectDeepSeekAccountToken(ctx,'exact-rejected-token')
 rows.push({kind:'account-token',name:mode,calls,...result})
}
console.log(JSON.stringify(rows))
