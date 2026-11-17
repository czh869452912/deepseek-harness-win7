import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {RRule}=await load('packages/util/time/src/rrule.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
function normalize(value:any):any{
 if(value instanceof Error)return {name:value.name,message:value.message}
 if(Array.isArray(value))return value.map(normalize)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)]))
 return value
}
for(const {op,args} of cases){
 try{
  const parsed=RRule.parse(args[0],op==='parse'?args[1]:undefined);let value
  if(parsed.kind==='rejected')value=normalize(parsed)
  else{
   const rule=parsed.rule
   if(op==='parse')value={kind:'accepted',expression:rule.expression,timeZone:rule.timeZone}
   else if(op==='next')value=rule.next(args[1])??null
   else if(op==='resolve')value=rule.resolve(...args.slice(1))
   else{const saved=rule.next(args[1]);value={scheduledAt:saved,decision:rule.resolve(saved,args[2])}}
  }
  rows.push({op,args,value})
 }catch(error:any){rows.push({op,args,error:{name:error.name,message:error.message}})}
}
console.log(JSON.stringify(rows))
