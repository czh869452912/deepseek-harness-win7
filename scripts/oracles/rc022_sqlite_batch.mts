import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const workspace=readFileSync(process.argv[3]!,'utf8'),{Config,SqliteStorageBackend}=await load('packages/storage/storage-sqlite/src/index.ts'),rows:any[]=[]
for(const operation of ['put','global','delete','batch','missing','empty','abort','rollback','stamp-failed']){
 let backend=new SqliteStorageBackend(new Config({path:join(workspace,'source-'+operation+'.db')})),unit:any
 try{
  unit=await backend.kv.open({name:'specimen',version:1,tables:['records'],hasGlobal:true})
  for(const key of ['a','b'])await unit.putRecord('records',key,{n:key})
  await unit.setGlobal({old:true});await unit.close()
  unit=await backend.kv.open({name:'specimen',version:2,tables:['records'],hasGlobal:true,compatibleVersions:[1]})
  let db=await backend.ready
  rows.push({operation,phase:'opened',version:db.prepare("SELECT version FROM units WHERE name='specimen'").get().version,state:await unit.loadAll()})
  if(['abort','rollback'].includes(operation))db.exec("CREATE TRIGGER refuse BEFORE DELETE ON u_specimen_records WHEN old.key='b' BEGIN SELECT RAISE("+operation.toUpperCase()+", 'blocked'); END")
  if(operation==='stamp-failed')db.exec("CREATE TRIGGER refuse BEFORE UPDATE ON units BEGIN SELECT RAISE(ABORT, 'stamp blocked'); END")
  let error=null
  try{
   if(operation==='put')await unit.putRecord('records','c',{new:true})
   else if(operation==='global')await unit.setGlobal({new:true})
   else if(operation==='delete')await unit.deleteRecord('records','a')
   else if(operation==='missing')await unit.deleteRecords('records',['missing','missing'])
   else if(operation==='empty')await unit.deleteRecords('records',[])
   else await unit.deleteRecords('records',['a','b','a','missing'])
  }catch(failure){error=(failure as Error).message}
  rows.push({operation,phase:'mutation',error,version:db.prepare("SELECT version FROM units WHERE name='specimen'").get().version,state:await unit.loadAll()})
  await unit.close();unit=undefined;await backend.close();backend=new SqliteStorageBackend(new Config({path:join(workspace,'source-'+operation+'.db')}))
  unit=await backend.kv.open({name:'specimen',version:2,tables:['records'],hasGlobal:true,compatibleVersions:[1]});rows.push({operation,phase:'reopened',state:await unit.loadAll()})
 }finally{await unit?.close();await backend.close()}
}
console.log(JSON.stringify(rows))
