import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {resolveAdapterOptions,isBuiltInCatalog}=await load('packages/llm/llm-deepseek/src/config.ts')
const {parseModelListing}=await load('packages/llm/llm-deepseek/src/listing.ts')
const {resolveListedCatalog,refuseListedModel}=await load('packages/llm/llm-deepseek/src/listed-catalog.ts')
const {APP_IDENTITY}=await load('packages/llm/llm/src/attribution.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [index,config] of inputs.configs.entries()){
 let result:any
 try{const value=resolveAdapterOptions(config);result={value,builtIn:isBuiltInCatalog(value.models)}}
 catch(error:any){result={error:error.message,code:error.code??null}}
 rows.push({kind:'config',index,...result})
}
const supported=resolveAdapterOptions({}).models
for(const [index,input] of inputs.catalogs.entries()){
 let result:any
 try{
  const listing=input.rows===null?undefined:input.rows.length===0?[]:parseModelListing({data:input.rows}).entries
  const catalog=resolveListedCatalog({listing,supported:structuredClone(supported),overrides:input.overrides,routeMaxTokens:256000,clientVersion:input.clientVersion??'0.2.2-rc.3'})
  const refused:Record<string,unknown>={}
  for(const [id,refusal] of catalog.refusals){
   try{refuseListedModel(id,refusal)}catch(error:any){
    if(!error.message.endsWith('current version is '+APP_IDENTITY.version))throw new Error('refusal runtime identity mismatch')
    refused[id]={error:error.message.slice(0,-APP_IDENTITY.version.length)+'<active-runtime>',code:error.code}
   }
  }
  result={value:{...catalog,refusals:Object.fromEntries(catalog.refusals),badges:Object.fromEntries(catalog.badges)},refused}
 }catch(error:any){result={error:error.message,code:error.code??null}}
 rows.push({kind:'catalog',index,...result})
}
console.log(JSON.stringify(rows))
