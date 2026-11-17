import {readFileSync} from 'node:fs'
import {mkdir,stat} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Workspace}=await load('packages/workspace/workspace/src/index.ts'),{JsonStorageBackend}=await load('packages/storage/storage-json/src/index.ts'),{DomainFacility}=await load('packages/storage/storage-domain/src/index.ts')
const {files}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
async function boot(directory:string){const ctx=new Context(),backend=new JsonStorageBackend(join(directory,'medium'));ctx.provide('storage',{backend:{get:()=>backend}} as any);const facility=new DomainFacility(ctx,{backend:'fixture'});ctx.provide('storageDomain',facility);ctx.provide('sessionPersistence',{list:async()=>[]} as any);ctx.provide('sessions',{get:()=>undefined,list:()=>[]} as any);await ctx.plugin(Workspace);return {ctx,backend,facility,registry:ctx.workspaceRegistry as any}}
const close=async(host:any)=>{await host.ctx.fiber.dispose();await host.facility.closeAll();await host.backend.close()}
const snapshot=(host:any)=>{const registry=host.registry,state=registry.global.get();return {order:state.workspaceIds.length,records:registry.table.size,cache:registry.list().length,default:state.defaultWorkspaceId!==undefined,pending:state.pendingMutation?.operation??null}}
let directory=join(files,'source-default');await mkdir(directory);let host=await boot(directory);const lookups:any[]=[]
const resolve=async()=>{lookups.push(true);return join(directory,'nested/Workspace')}
try{const [first,last]=await Promise.all([host.registry.initializeDefault(resolve),host.registry.initializeDefault(resolve)]);rows.push({step:'concurrent',same:first===last,title:first.title,exists:(await stat(first.path)).isDirectory(),lookups:lookups.length,state:snapshot(host)});await first.setTitle('Renamed');await close(host);host=await boot(directory);let found=await host.registry.initializeDefault(resolve);rows.push({step:'reopened',title:found.title,lookups:lookups.length,state:snapshot(host)});await host.registry.delete(found.id);await close(host);host=await boot(directory);found=await host.registry.initializeDefault(resolve);rows.push({step:'deleted',absent:found===undefined,lookups:lookups.length,state:snapshot(host)})}finally{await close(host)}
for(const mode of ['record','record-rollback','order','order-delete-rollback','order-state-rollback','delete-cleanup','delete-state-rollback']){
 const directory=join(files,'source-'+mode);await mkdir(directory);let host=await boot(directory);const registry=host.registry,path=join(directory,'project');await mkdir(path);let entity:any
 if(mode.startsWith('delete'))entity=await registry.create(path)
 const global=registry.global,table=registry.table,originalState=global.set.bind(global),originalPut=table.put.bind(table),originalDelete=table.delete.bind(table),stateCalls:any[]=[]
 global.set=async(value:any)=>{stateCalls.push(value);const failing=['order','order-delete-rollback','delete-cleanup'].includes(mode)?[2]:mode==='order-state-rollback'?[2,3]:['record-rollback','delete-state-rollback'].includes(mode)?[2]:[];if(failing.includes(stateCalls.length))throw Error('selected state write');await originalState(value)}
 table.put=async(...args:any[])=>{if(mode.startsWith('record'))throw Error('selected record write');return await originalPut(...args)}
 table.delete=async(...args:any[])=>{if(['order-delete-rollback','delete-state-rollback'].includes(mode))throw Error('selected record delete');return await originalDelete(...args)}
 try{let error:any=null;try{mode.startsWith('delete')?await registry.delete(entity.id):await registry.create(path)}catch(exc:any){error={name:exc.name??'Error',causes:(exc.errors??[]).map((item:any)=>item.message)}}rows.push({step:mode,error,state:snapshot(host)});global.set=originalState;table.put=originalPut;table.delete=originalDelete;await close(host);host=await boot(directory);rows.push({step:mode+'-reopened',state:snapshot(host)})}finally{await close(host)}
}
console.log(JSON.stringify(rows))
