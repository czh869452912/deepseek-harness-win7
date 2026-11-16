import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const notifications=await load('packages/credentials/deepseek-account/src/notifications.ts')
const protocol=await load('packages/credentials/deepseek-account/src/protocol.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],logs:any[]=[],original=globalThis.fetch,log=console.error
try{
 console.error=(label:any,value:any)=>logs.push({label:String(label).replace('[deepseek-account] ',''),...value})
 for(const [index,entry] of inputs.entries()){
  const start=logs.length,kind=entry.kind;let result:any
  if(['initialization','exchange'].includes(kind)){
   const parsed=protocol[kind].safeParse(entry.value)
   result=parsed.success?{value:parsed.data}:{issues:parsed.error.issues.map((issue:any)=>({path:issue.path,code:issue.code}))}
  }else{
   globalThis.fetch=async()=>new Response(JSON.stringify({code:0,data:{biz_code:0,biz_data:entry.value}}))
   try{
    let value:any;const args=['https://platform.example','fixture-token'],tail=[new AbortController().signal,{}]
    if(kind==='list')value=await notifications.readNotifications(...args,...tail)
    else if(kind==='content')value=await notifications.readNotificationContent(...args,'notice',...tail)
    else{await notifications.sendNotificationEvent(...args,'notice','dismissed',...tail);value='<void>'}
    result={value}
   }catch(error:any){result={error:{message:error.message,code:error.code??null}}}
  }
  rows.push({index,result,diagnostics:logs.slice(start)})
 }
}finally{globalThis.fetch=original;console.error=log}
process.stdout.write(JSON.stringify(rows))
