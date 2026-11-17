import {readFileSync,mkdirSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {scheduleTaskSchema}=await load('packages/schedule/schedule/src/storage.ts')
const {appendDelivery,deliveryHistoryPage}=await load('packages/schedule/schedule/src/delivery-history.ts')
const {JsonStorageBackend}=await load('packages/storage/storage-json/src/index.ts')
const {cases,files}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
const descriptor={name:'schedule',version:2,compatibleVersions:[1],tables:['tasks'],hasGlobal:false}
for(const [index,entry] of cases.entries()){
 const parsed=scheduleTaskSchema.safeParse(entry.task),op=entry.op
 if(!parsed.success){
  const issues=parsed.error.issues.map(({code,path}:any)=>({code,path})).sort((a:any,b:any)=>JSON.stringify(a).localeCompare(JSON.stringify(b),'en'))
  rows.push({op,success:false,issues});continue
 }
 const task=parsed.data;let value
 if(op==='parse')value=task
 else if(op==='page')value=deliveryHistoryPage(task,entry.request,entry.bounds)
 else if(op==='append')value=appendDelivery(task,entry.receipt,entry.bounds)
 else{
  const folder=join(files,'source-'+index);mkdirSync(folder);const path=join(folder,'schedule.json')
  const before=JSON.stringify({unit:{name:'schedule',version:1},global:null,tables:{tasks:{id:entry.task}}});writeFileSync(path,before,'utf8')
  const backend=new JsonStorageBackend(folder)
  try{
   let unit=await backend.kv.open(descriptor);const normalized=scheduleTaskSchema.parse((await unit.loadAll()).tables.tasks.id)
   const unchanged=readFileSync(path,'utf8')===before;await unit.putRecord('tasks','id',{...normalized,updatedAt:'2026-09-16T00:01:00.000Z'});await unit.close()
   unit=await backend.kv.open(descriptor)
   value={normalized,unchanged,disk:JSON.parse(readFileSync(path,'utf8')),cold:scheduleTaskSchema.parse((await unit.loadAll()).tables.tasks.id)}
  }finally{await backend.close()}
 }
 rows.push({op,success:true,value})
}
console.log(JSON.stringify(rows))
