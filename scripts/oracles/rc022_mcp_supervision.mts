import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const load=(name:string)=>import(pathToFileURL(path.join(root,name)).href)
const {Context}=await load('vendor/cordis/src/index.ts')
const {startConnection,resolveReconnectPolicy}=await load('packages/mcp/mcp-client/src/connection.ts')
const {McpStatusCell}=await load('packages/mcp/mcp-client/src/status.ts')
const {describeError}=await load('packages/mcp/mcp-client/src/diagnostic.ts')
const {Config}=await load('packages/mcp/mcp-client/src/index.ts')
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const {Client}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')).href)
const clients:any[]=[],original=Client.prototype.connect
Client.prototype.connect=function(...args:any[]){clients.push(this);return original.apply(this,args)}
const normalize=(value:any):any=>Array.isArray(value)?value.map(normalize):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,v])=>[key,['connectedAt','nextRetryAtMs'].includes(key)?0:normalize(v)])):value
const records=()=>fs.existsSync(input.log)?fs.readFileSync(input.log,'utf8').split('\n').filter(Boolean).map(line=>JSON.parse(line)):[]
async function wait(predicate:()=>boolean){for(let i=0;i<1000;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,5))}throw new Error('condition timed out')}
const rows=[]
try{
 for(const [index,mode] of input.cases.entries()){
  const ctx=new Context(),names=new Set<string>(),trace:any[]=[],values=new Map<string,string>(),logs:any[]=[]
  for(const level of ['info','warn','error'])ctx.logger[level]=(...args:any[])=>logs.push({level,message:String(args[0])})
  ctx.provide('tools',{register(spec:any){
   if(names.has(spec.name))throw new Error('occupied')
   names.add(spec.name)
   return ()=>{names.delete(spec.name);if(mode==='tool-cleanup-error')throw new Error('cleanup synthetic/token')}
  }})
  ctx.provide('credentials',{resolve:async(ref:string)=>values.has(ref)?{value:values.get(ref)}:undefined})
  const wireMode=mode==='startup-timeout'?'hold':['modern','none'].includes(mode)?mode:'legacy',urlPath='/source/'+index+'/'+wireMode
  const config:any={transport:'streamable-http',serverName:'supervised',url:input.url+urlPath,headers:{},closeTimeoutMs:500,toolCallTimeoutMs:60000,reconnect:{enabled:false}}
  if(mode==='startup-timeout')config.startupTimeoutMs=100
  if(['credentials','tool-cleanup-error'].includes(mode)){
   config.expandTemplates=true;config.headers={Authorization:'Bearer ${credential:TOKEN}'}
   if(mode==='tool-cleanup-error')values.set('TOKEN','synthetic/token')
  }
  if(mode==='reconnect-budget')config.reconnect={enabled:true,initialDelayMs:5,maxDelayMs:10000,maxAttempts:1}
  if(mode==='registration-conflict')names.add('mcp__supervised__a')
  const cell=new McpStatusCell(()=>{});cell.onChange((status:any)=>{trace.push(normalize({...status}))})
  const connection=startConnection(ctx,config,resolveReconnectPolicy(config.reconnect,'fixture'),cell)
  try{
   const ready=await connection.ready,checkpoints:any[]=[]
   const snapshot=()=>({status:normalize(cell.current()),closure:cell.closure(),names:[...names].sort(),instructions:connection.instructions()})
   checkpoints.push(snapshot())
   if(mode==='credentials'){
    values.set('TOKEN','synthetic/token');ctx.emit('credentials/reference-updated','TOKEN')
    await wait(()=>cell.current().state==='connected');checkpoints.push(snapshot())
    const before=trace.length;ctx.emit('credentials/reference-updated','UNRELATED');ctx.emit('credentials/reference-updated','TOKEN');await new Promise(resolve=>setTimeout(resolve,25))
    if(trace.length!==before)throw new Error('unchanged credential reconnected')
    values.set('TOKEN','rotated/token');ctx.emit('credentials/reference-updated','TOKEN')
    await wait(()=>trace.length>before&&cell.current().state==='connected');checkpoints.push(snapshot())
    values.clear();ctx.emit('credentials/reference-updated','TOKEN')
    await wait(()=>cell.current().state==='waiting-credentials');checkpoints.push(snapshot())
   }
   if(mode==='reconnect-budget'){
    const first=clients.at(-1);await first.transport.close()
    await wait(()=>clients.at(-1)!==first&&cell.current().state==='connected');checkpoints.push(snapshot())
    await clients.at(-1).transport.close()
    await wait(()=>cell.current().reason==='gave-up'&&names.size===0);checkpoints.push(snapshot())
   }
   await connection.dispose();checkpoints.push(snapshot())
   const wire=records().filter(item=>item.path===urlPath&&item.packet.method!=='notifications/cancelled').map(item=>({method:item.packet.method,authorization:item.authorization}))
   rows.push({mode,ready:ready.error===undefined?{}:{error:describeError(ready.error)},trace,checkpoints,wire,logs})
  }finally{await connection.dispose();await ctx.fiber.dispose()}
 }
 for(const config of input.configs){
  let result
  try{result={data:Config(config)}}catch(error){result={error:{name:error.name,message:error.message}}}
  rows.push({config,result})
 }
 process.stdout.write(JSON.stringify(rows))
}finally{Client.prototype.connect=original}
