import {readFileSync} from 'node:fs'
import {readFile,writeFile,mkdir,readdir,stat} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const workspace=readFileSync(process.argv[3]!,'utf8'),{JsonStorageBackend}=await load('packages/storage/storage-json/src/index.ts'),rows:any[]=[]
for(const bootstrap of [false,true]){
 const root=join(workspace,'source-'+bootstrap);await mkdir(root)
 const descriptor={name:'batch',version:2,tables:['t'],hasGlobal:true,layout:'per-record',compatibleVersions:[1]},legacy=JSON.stringify({unit:{name:'batch',version:1},tables:{t:{a:{n:1},b:{n:2}}}})
 if(bootstrap)await writeFile(join(root,'batch.json'),legacy)
 const backend=new JsonStorageBackend(root);let unit=await backend.kv.open(descriptor)
 try{
  rows.push({bootstrap,phase:'opened',state:await unit.loadAll()})
  if(!bootstrap){await unit.putRecord('t','a',{n:1});await unit.putRecord('t','b',{n:2})}
  await unit.deleteRecords('t',['missing','a','a']);rows.push({bootstrap,phase:'first',state:await unit.loadAll()})
  await unit.deleteRecord('t','b');await unit.deleteRecords('t',[])
  rows.push({bootstrap,phase:'empty',state:await unit.loadAll(),tableExists:(await stat(join(root,'batch/t'))).isDirectory(),files:(await readdir(join(root,'batch/t'))).sort()})
  await unit.close();unit=await backend.kv.open(descriptor)
  rows.push({bootstrap,phase:'reopened',state:await unit.loadAll(),legacyUnchanged:!bootstrap||(await readFile(join(root,'batch.json'),'utf8'))===legacy})
  await unit.putRecord('t','receipt',{done:true});const saved=await readFile(join(root,'batch/t/receipt.json')),backup=await unit.backupRecord('t','receipt')
  rows.push({bootstrap,phase:'backup',state:await unit.loadAll(),sameBytes:saved.equals(await readFile(backup)),backupIgnored:!backup.endsWith('.json')})
 }finally{await unit.close();await backend.close()}
}
console.log(JSON.stringify(rows))
