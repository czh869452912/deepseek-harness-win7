import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Cron}=await load('packages/util/time/src/cron.ts'),domain=await load('packages/schedule/schedule/src/domain.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
function normalize(value:any):any{
 if(value instanceof Error)return {name:value.name,message:value.message}
 if(Array.isArray(value))return value.map(normalize)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)]))
 return value
}
for(const {op,args} of cases){
 try{
  let value
  if(['parse','next','resolve','journey'].includes(op)){
   const parsed=Cron.parse(...args.slice(0,2))
   if(parsed.kind==='rejected')value=parsed
   else{
    const rule=parsed.rule
    if(op==='parse')value={kind:'accepted',fields:rule.fields,timeZone:rule.timeZone,expression:rule.expression}
    else if(op==='next')value=rule.next(args[2])??null
    else if(op==='resolve')value=rule.resolve(...args.slice(2))
    else{const saved=rule.next(args[2]);value={scheduledAt:saved,decision:rule.resolve(saved,args[3])}}
   }
  }else value=domain[op==='decodeCronRecord'?'decodeScheduleRecord':op](...args)
  rows.push({op,args,value:normalize(value)})
 }catch(error:any){rows.push({op,args,error:{name:error.name,code:error.code??null,message:error.message}})}
}
console.log(JSON.stringify(rows))
