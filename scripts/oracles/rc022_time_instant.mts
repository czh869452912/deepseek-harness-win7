import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const instant=await load('packages/util/time/src/instant.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
for(const {op,args} of cases){
 try{
  let value=op==='resolve'?instant.resolveLocalInstant(instant.parseLocalCalendar(...args.slice(0,2)).time,args[2]):op==='resolveParts'?instant.resolveLocalInstant(...args):instant[op](...args)
  if(value?.cause)value={...value,cause:{name:value.cause.name,message:value.cause.message}}
  rows.push({op,args,value:value??null})
 }catch(error:any){rows.push({op,args,error:error.name})}
}
console.log(JSON.stringify(rows))
