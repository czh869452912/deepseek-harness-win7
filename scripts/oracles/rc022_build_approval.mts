import {readFileSync,existsSync} from 'node:fs'
import {mkdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const policy=await load('packages/boot/plugin-manager/src/build-approval.ts'),input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const item of input.cases){
 const dir=join(input.workspace,'source',item.name);await mkdir(dir,{recursive:true});const path=join(dir,'pnpm-workspace.yaml')
 if(item.text!==null)await writeFile(path,item.text)
 const content=()=>existsSync(path)?readFileSync(path,'utf8'):null,initial=content()
 async function result(operation:any){try{return {value:await operation()}}catch(error:any){return {error:error.code==='stale-approval'?'stale-approval':'error'}}}
 const recorded=await result(()=>policy.recordPendingBuilds(dir,item.output)),before=content(),approved=await result(()=>policy.approveBuilds(dir,item.approve)),after=content(),pending=await result(()=>policy.recordPendingBuilds(dir,''))
 rows.push({name:item.name,blocked:policy.blockedBuildNames(item.output),recorded,approved,pending,recordedChanged:before!==initial,approvedChanged:before!==after,exists:existsSync(path),comments:after!==null&&after.includes('# settings'),unrelated:after!==null&&after.includes('&unrelated value')})
}
console.log(JSON.stringify(rows))
