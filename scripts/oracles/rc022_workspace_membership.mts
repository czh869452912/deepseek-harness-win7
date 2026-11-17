import {readFileSync} from 'node:fs'
import {mkdir,rmdir} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Workspace}=await load('packages/workspace/workspace/src/index.ts'),{JsonStorageBackend}=await load('packages/storage/storage-json/src/index.ts'),{DomainFacility}=await load('packages/storage/storage-domain/src/index.ts')
const {files}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),directory=join(files,'source'),project=join(directory,'project'),elsewhere=join(directory,'elsewhere'),stored:any[]=[],rows:any[]=[],live=new Map()
await mkdir(project,{recursive:true});await mkdir(elsewhere)
const header=(id:string,cwd?:string)=>({id,createdAt:0,...(cwd===undefined?{}:{cwd})})
async function boot(medium='medium'){
 const ctx=new Context(),backend=new JsonStorageBackend(join(directory,medium));ctx.provide('storage',{backend:{get:()=>backend}} as any)
 const facility=new DomainFacility(ctx,{backend:'fixture'});ctx.provide('storageDomain',facility)
 ctx.provide('sessionPersistence',{list:async()=>stored.map(value=>({header:value,revision:'r'}))} as any)
 ctx.provide('sessions',{get:(id:string)=>live.get(id),list:()=>[...live.values()]} as any)
 await ctx.plugin(Workspace);return {ctx,backend,facility,registry:ctx.workspaceRegistry as any}
}
const close=async(host:any)=>{await host.ctx.fiber.dispose();await host.facility.closeAll();await host.backend.close()}
let host=await boot(),entity=await host.registry.create(project);const identity=entity.id
function clean(value:any):any{if(typeof value==='string')return value.replaceAll(directory,'ROOT').replaceAll('\\','/');if(Array.isArray(value))return value.map(clean);if(value!==null&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,clean(item)]));return value}
async function step(name:string,work?:any){let error:any;try{if(work)await work()}catch(exc:any){error={message:exc.message}}rows.push(clean({step:name,ids:[...entity.sessionIds],stored:host.registry.table.get(identity).sessionIds,status:await entity.status(),...(error===undefined?{}:{error})}))}
try{
 stored.splice(0,stored.length,header('first',project),header('second',project),header('unowned',project))
 await step('attach-first',()=>entity.attachSession('first'));await step('attach-second',()=>entity.attachSession('second'))
 await close(host);await rmdir(project);host=await boot();entity=host.registry.get(identity)
 await step('missing-reopen');await step('missing-title-write',()=>entity.setTitle('Still owned'))
 await step('missing-manual-order',()=>entity.insertSessionBefore('first','second'));await step('missing-new-attach',()=>entity.attachSession('unowned'))
 await close(host);host=await boot();entity=host.registry.get(identity);await step('second-reopen')
 stored.splice(0,stored.length,header('first',elsewhere),header('second',project),header('trigger-one',elsewhere));await step('fresh-header-moves-first',()=>host.registry.pinSession('trigger-one'))
 stored.splice(0,stored.length,header('first',project),header('second',project),header('trigger-two',elsewhere));await step('fresh-header-missing-again',()=>host.registry.pinSession('trigger-two'))
 stored.splice(0,stored.length,header('first'),header('second',project),header('trigger-three',elsewhere));await step('fresh-header-without-cwd',()=>host.registry.pinSession('trigger-three'))
 await step('write-prunes-invalid',()=>entity.setTitle('Validated'));await step('detach-missing',()=>entity.detachSession('second'))
 await mkdir(project);stored.splice(0,stored.length,header('second',project));await step('restore-reattach',()=>entity.attachSession('second'))
 await close(host);stored.length=0;host=await boot();entity=host.registry.get(identity);await step('absent-header-cold-reopen');await step('write-prunes-absent',()=>entity.setTitle('No history'))
 await close(host);await rmdir(project);stored.splice(0,stored.length,header('unowned',project));host=await boot('fresh-medium');rows.push({step:'missing-never-bootstraps',workspaces:host.registry.list().length})
}finally{await close(host)}
console.log(JSON.stringify(rows))
