import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const rrule=await load('node_modules/.pnpm/rrule@2.8.1/node_modules/rrule/dist/es5/rrule.js'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
for(const query of cases){
 const basic=new Date(query.anchor).toISOString().replaceAll('-','').replaceAll(':','').slice(0,15)
 const rule=rrule.rrulestr(`DTSTART:${basic}Z\n${query.recurrence}`)
 if(query.mode==='after')rows.push(rule.after(new Date(query.from_wall),true)?.getTime()??null)
 else{
  const result:number[]=[]
  rule.all((date:Date)=>{
   const wall=date.getTime();if(wall<query.from_wall)return true
   result.push(wall);return result.length<query.limit&&(query.through===null||wall<=query.through)
  });rows.push(result)
 }
}
console.log(JSON.stringify(rows))
