import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const load=(name:string)=>import(pathToFileURL(path.join(root,name)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Manager}=await load('packages/mcp/mcp-manager/src/index.ts')
const normalize=(value:any):any=>Array.isArray(value)?value.map(normalize):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([k,v])=>[k,k==='connectedAt'?0:normalize(v)])):value
async function wait(predicate:()=>boolean){for(let i=0;i<1000;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,5))}throw new Error('condition timed out')}
const ctx=new Context(),names=new Set<string>(),rows:any[]=[]
ctx.provide('tools',{register(spec:any){if(names.has(spec.name))throw new Error('occupied');names.add(spec.name);return ()=>names.delete(spec.name)}})
const entry={transport:'streamable-http',url:input.url+'/source/fleet/legacy',enabled:false}
const fiber=ctx.plugin(Manager,{servers:{fleet:entry}});await fiber.await();const manager=ctx.get('mcpManager')
const snapshot=(step:string)=>rows.push({step,views:normalize(manager.list()),names:[...names].sort()})
try{
 await wait(()=>manager.list()[0].status.state==='disabled');snapshot('disabled')
 const result=await manager.probe('fleet');delete result.durationMs;rows.push({step:'probe',result});snapshot('probe-independent')
 const controller=new AbortController(),stream=manager.watch(controller.signal)
 rows.push({step:'watch-first',views:normalize((await stream.next()).value)})
 const next=Manager.Config({servers:{fleet:{...entry,enabled:true}}})
 manager.config.servers[Symbol.for('cosmokit.volatile.write')](next.servers.get());manager.ctx.emit('loader/volatile-update',[])
 await wait(()=>manager.list()[0].status.state==='connected');snapshot('enabled')
 rows.push({step:'watch-updated',views:normalize((await stream.next()).value)})
 await manager.restart('fleet');await wait(()=>manager.list()[0].status.state==='connected');snapshot('restarted')
 const contributor=ctx.plugin((child:any)=>{child.get('mcpManager').register('contributed',{transport:'streamable-http',url:input.url+'/source/contributed/modern'})});await contributor.await()
 await wait(()=>manager.list().length===2&&manager.list()[1].status.state==='connected');snapshot('registered')
 await contributor.dispose();await wait(()=>manager.list().length===1);snapshot('unregistered')
 for(const operation of ['restart','probe']){try{await manager[operation]('absent')}catch(error){rows.push({step:'unknown-'+operation,error:String(error)})}}
 controller.abort();if(!(await stream.next()).done)throw new Error('watch did not stop')
 await fiber.dispose();snapshot('disposed')
 try{await manager.restart('fleet')}catch(error){rows.push({step:'stopped',error:String(error)})}
 process.stdout.write(JSON.stringify(rows))
}finally{await ctx.fiber.dispose()}
