import fs from 'node:fs'
import path from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const {Context}=await load('vendor/cordis/src/index.ts'),rows=[]
for(const capabilities of [true,false]){
 const ctx=new Context(),dir=path.join(input.output,'source-'+String(capabilities));fs.mkdirSync(dir)
 const log=path.join(dir,'peer.jsonl'),counter=path.join(dir,'counter.txt')
 for(const file of ['packages/core/system-prompt/src/index.ts','packages/core/tools/src/index.ts','packages/core/tool-executor-native/src/index.ts','packages/mcp/mcp-resources/src/index.ts']){
  const module=await load(file);await ctx.plugin(module.default??module)
 }
 try{
  const client=await load('packages/mcp/mcp-client/src/index.ts')
  const fiber=await ctx.plugin(client,{transport:'stdio',serverName:'docs',command:input.python,args:[input.peer,log,counter,capabilities?'resources':'none'],reconnect:{enabled:false},failOnStartupError:true})
  const exec={signal:new AbortController().signal}
  const values=[]
  for(const request of [{method:'resources/list',cursor:''},{method:'resources/templates/list'},{method:'resources/read',uri:'doc://a'}])values.push(await (ctx.mcpResources as any).request('docs',request,exec))
  const assembled=await ctx.systemPrompt.assemble(),instructions=assembled.sections.find((row:any)=>row.name==='mcp:docs')
  await fiber.dispose()
  const methods=fs.readFileSync(log,'utf8').trim().split('\n').map(line=>JSON.parse(line).packet).filter(packet=>packet.method.startsWith('resources/'))
  rows.push({capabilities,values,instructions,requests:methods.map(({method,params}:any)=>({method,...params===undefined?{}:{params}})),toolsAfter:ctx.tools.schemas().map((row:any)=>row.name)})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
