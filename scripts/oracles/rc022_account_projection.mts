import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const metadata=await load('packages/credentials/deepseek-account/src/client-metadata.ts')
const details=await load('packages/credentials/deepseek-account/src/details.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],original=globalThis.fetch,log=console.error
try{
 console.error=()=>{}
 for(const [index,entry] of input.entries()){
  let value:any
  if(entry.kind==='cookies')value=metadata.mergePlatformCookies(entry.base,entry.override)
  else if(entry.kind==='headers')value={headers:metadata.platformClientHeaders(entry.platform,entry.client),locale:metadata.platformWireLocale(entry.client.locale)}
  else if(entry.kind==='profile'){
   try{value=details.profile(entry.value)}catch(error:any){value={error:{code:error.code,message:error.message}}}
  }else{
   globalThis.fetch=async()=>new Response(JSON.stringify({code:0,data:{biz_code:0,biz_data:entry.value}}))
   value=await details.readAccountDetail('balance','https://platform.example','fixture-token',new AbortController().signal,{})
  }
  rows.push({index,value})
 }
}finally{globalThis.fetch=original;console.error=log}
process.stdout.write(JSON.stringify(rows))
