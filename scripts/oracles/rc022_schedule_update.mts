import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const domain=await load('packages/schedule/schedule/src/domain.ts'),update=await load('packages/schedule/schedule/src/update.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
const now=Date.parse('2026-09-16T00:00:00Z')
for(const {op,args} of cases){
 try{
  let value
  if(op==='editJourney'||op==='decodeJourney'){
   const current=update.createScheduleRecord('id','title','prompt',args[0],now)
   const revised=op==='editJourney'?update.updateScheduleRecord(current,...args.slice(1)):domain.decodeScheduleRecord(current)
   value={current,record:revised,same:current===revised}
  }else value=(update[op]??domain[op])(...args)
  rows.push({op,args,value})
 }catch(error:any){rows.push({op,args,error:{name:error.name,code:error.code??null,message:error.message}})}
}
console.log(JSON.stringify(rows))
