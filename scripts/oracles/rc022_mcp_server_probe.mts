import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const {Context}=await import(pathToFileURL(path.join(root,'vendor/cordis/src/index.ts')).href)
const {probeServer}=await import(pathToFileURL(path.join(root,'packages/mcp/mcp-client/src/probe.ts')).href)
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const {Client,StreamableHTTPClientTransport}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')).href)
function normalize(error:any){return {name:error.name,message:error.message,...error.code!==undefined?{code:error.code}:{},...error.data!==undefined?{data:error.data}:{}}}
const records=()=>fs.existsSync(input.log)?fs.readFileSync(input.log,'utf8').split('\n').filter(Boolean).map(line=>JSON.parse(line)):[]
const rows=[]
for(const [index,row] of input.cases.entries()){
 const ctx=new Context(),controller=new AbortController(),urlPath='/source/'+index+'/'+row.mode
 ctx.provide('credentials',{resolve:async()=>row.binding==='present'?{value:'synthetic/token'}:undefined})
 const config={transport:'streamable-http',serverName:'inspect',url:input.url+urlPath,closeTimeoutMs:500,headers:{},...row.binding?{expandTemplates:true,headers:{Authorization:'Bearer ${credential:TOKEN}'}}:{}}
 let result
 try{
  const pending=(async()=>{
   if(!row.aggregate)return await probeServer(ctx,config,{...row.options,signal:controller.signal})
   const client=new Client({name:'dsh-mcp-probe',version:'0.0.1'},{capabilities:{},versionNegotiation:{mode:'auto'}})
   const transport=new StreamableHTTPClientTransport(new URL(config.url))
   try{await client.connect(transport);return {listing:await client.listTools(row.cursor?{cursor:'next'}:undefined)}}
   finally{await client.close();await transport.close()}
  })()
  if(row.abort){
   for(let attempt=0;attempt<1000;attempt++){
    if(records().some(item=>item.path===urlPath&&item.packet.method==='tools/list'))break
    await new Promise(resolve=>setTimeout(resolve,5))
   }
   controller.abort(new Error('controlled abort'))
  }
  result=await pending
  if(!row.aggregate){if(typeof result.durationMs!=='number')throw new Error('missing duration');delete result.durationMs}
 }catch(error){result={thrown:normalize(error)}}
 finally{await ctx.fiber.dispose()}
 const packets=records().filter(item=>item.path===urlPath).map(item=>item.packet).filter(packet=>packet.method!=='notifications/cancelled')
 const budget=row.options.timeoutMs
 rows.push({case:row,result,packets:typeof budget==='number'&&(budget>2147483647||budget>0&&budget<1)?'timing-dependent; raw log retained':packets})
}
process.stdout.write(JSON.stringify(rows))
