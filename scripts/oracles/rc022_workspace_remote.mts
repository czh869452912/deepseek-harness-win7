import {readFileSync,mkdirSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Workspace}=await load('packages/workspace/workspace/src/index.ts'),{default:Controller}=await load('packages/api/workspace-controller/src/index.ts'),{JsonStorageBackend}=await load('packages/storage/storage-json/src/index.ts'),{DomainFacility}=await load('packages/storage/storage-domain/src/index.ts')
const {files}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),ctx=new Context(),rows:any[]=[],aliases=new Map<string,string>(),hidden=new Set<string>(),live=new Map(['shared','secret'].map(id=>[id,{header:{id,createdAt:0}}]))
const backend=new JsonStorageBackend(join(files,'source'));ctx.provide('storage',{backend:{get:()=>backend}} as any)
const facility=new DomainFacility(ctx,{backend:'fixture'});ctx.provide('storageDomain',facility)
ctx.provide('sessionPersistence',{list:async()=>[]} as any);ctx.provide('sessions',{get:(id:string)=>live.get(id),list:()=>[...live.values()]} as any)
ctx.provide('remoteAccess',{allows:(resource:any)=>!hidden.has(resource.id)} as any)
await ctx.plugin(Workspace)
ctx.provide('typert',{resources:{register:()=>()=>{}}} as any)
const controller=new Controller(ctx,{documentsDirectory:files}),abort=new AbortController();let feed=controller.follow(abort.signal)[Symbol.asyncIterator]()
function project(value:any):any {if(Array.isArray(value))return value.map(project);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([key])=>!['path','createdAt','updatedAt'].includes(key)).map(([key,item])=>[key,project(item)]));return typeof value==='string'?(aliases.get(value)??value):value}
async function take(){const next=await feed.next();if(next.done)throw Error('unexpected feed end');rows.push(project(next.value))}
async function error(method:string,request:any){try{await (controller as any)[method](request)}catch(exc:any){rows.push({step:method,failure:project({code:exc.code,message:exc.message,details:exc.details})});return}throw Error('expected Remote failure')}
try{
 await take()
 for(const name of ['first','second']){const path=join(files,name);mkdirSync(path,{recursive:true});const result=await controller.create({path});aliases.set(result.workspace.workspaceId,name);rows.push({step:'create',created:result.created,title:result.workspace.title});await take();await take()}
 const ids=Object.fromEntries([...aliases].map(([id,name])=>[name,id]))
 rows.push({step:'reuse',created:(await controller.create({path:join(files,'first')})).created})
 await controller.pinSession({sessionId:'shared'});await take();await controller.pinSession({sessionId:'secret'});await take()
 await feed.return?.();hidden.add('secret');feed=controller.follow(abort.signal)[Symbol.asyncIterator]();await take()
 await controller.archiveSession({sessionId:'secret'});await take();await take()
 await error('pinSession',{sessionId:'secret'});await error('pinSession',{sessionId:'missing'});await error('archiveSession',{sessionId:'missing'})
 const remove=ctx.on('workspace/session-activity',()=>[{kind:'turn'}]);await error('archiveSession',{sessionId:'shared'});remove()
 await controller.unarchiveSession({sessionId:'secret'});await take()
 hidden.add(ids.first!);await controller.rename({workspaceId:ids.first!,title:'revoked'});await take()
 hidden.delete(ids.first!);await controller.rename({workspaceId:ids.first!,title:'restored'});await take()
 hidden.add(ids.second!);await controller.insertBefore({workspaceId:ids.first!,beforeWorkspaceId:ids.second!});await take()
 await controller.delete({workspaceId:ids.second!});await take()
 await controller.delete({workspaceId:ids.first!});await take();await take()
 await feed.return?.();feed=controller.follow(abort.signal)[Symbol.asyncIterator]();await take();abort.abort();rows.push({step:'aborted',ended:(await feed.next()).done===true})
}finally{await feed.return?.();await ctx.fiber.dispose();await facility.closeAll();await backend.close()}
console.log(JSON.stringify(rows))
