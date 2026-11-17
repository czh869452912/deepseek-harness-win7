import {readFileSync,mkdirSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {JsonStorageBackend}=await load('packages/storage/storage-json/src/index.ts'),{parse}=await load('packages/storage/storage-json/src/format.ts')
const {cases,files}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
const descriptor={name:'shape',version:2,compatibleVersions:[1],tables:['t'],hasGlobal:true}
for(const [index,entry] of cases.entries()){
 try{
  let value:any
  if(entry.op==='parse'){
   const parsed=parse(entry.text??JSON.stringify(entry.document),descriptor)
   value={...parsed,tables:Object.fromEntries([...parsed.tables].map(([name,records]:any)=>[name,Object.fromEntries(records)]))}
  }else{
   const folder=join(files,'source-'+index);mkdirSync(folder);const path=join(folder,'shape.json'),before=JSON.stringify(entry.document)
   writeFileSync(path,before,'utf8');const backend=new JsonStorageBackend(folder);let unit=await backend.kv.open(descriptor);value={}
   try{
    const op=entry.op
    if(op==='put')await unit.putRecord('t','d',4)
    else if(op==='deleteMissing')await unit.deleteRecords('t',['missing','missing'])
    else if(op==='deleteBatch')await unit.deleteRecords('t',['a','c','missing','a'])
    else if(op==='global')await unit.setGlobal({saved:true})
    else if(op==='reopen'){await unit.close();unit=await backend.kv.open(descriptor)}
    else if(op==='drain'){const write=unit.putRecord('t','d',4);await unit.close();await write}
    else if(op==='concurrentOpen'){
     await unit.close();const outcome=await Promise.allSettled([backend.kv.open(descriptor),backend.kv.open(descriptor)])
     unit=(outcome[0] as any).value;value.secondRejected=outcome[1].status==='rejected'
    }
    value={...value,snapshot:op==='drain'?null:await unit.loadAll(),unchanged:readFileSync(path,'utf8')===before,disk:JSON.parse(readFileSync(path,'utf8'))}
   }finally{await backend.close()}
  }
  rows.push({op:entry.op,value})
 }catch(error:any){rows.push({op:entry.op,error:{code:error.code??null,message:error.message}})}
}
console.log(JSON.stringify(rows))
