import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const domain=await load('packages/schedule/schedule/src/domain.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
for(const {op,args} of cases){
 try{
  let value
  if(op==='journey'){
   const [selector,input,now,decision]=args,name=selector[0].toUpperCase()+selector.slice(1)
   value=domain['resolve'+name+'Occurrence'](domain['create'+name+'ScheduleRecord']('id','prompt',input,now,'title'),decision)
  }else value=domain[op==='decodeWallRecord'?'decodeScheduleRecord':op](...args)
  rows.push({op,args,value})
 }catch(error:any){rows.push({op,args,error:{name:error.name,code:error.code??null,message:error.message}})}
}
console.log(JSON.stringify(rows))
