import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const domain=await load('packages/schedule/schedule/src/domain.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
for(const {op,args} of cases){
 try{rows.push({op,args,value:domain[op==='decodeIntervalRecord'?'decodeScheduleRecord':op](...args)})}
 catch(error:any){rows.push({op,args,error:{name:error.name,code:error.code??null,message:error.message}})}
}
console.log(JSON.stringify(rows))
