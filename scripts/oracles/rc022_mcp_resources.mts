import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),ctx=new Context()
const {createScope,bindScopeParent}=await load('packages/core/scope/src/index.ts')
const {renderResourceResult}=await load('packages/mcp/mcp-resources/src/render.ts')
for(const file of ['packages/core/system-prompt/src/index.ts','packages/core/tools/src/index.ts','packages/core/tool-executor-native/src/index.ts','packages/mcp/mcp-resources/src/index.ts']){
 const module=await load(file);await ctx.plugin(module.default??module)
}
const owner={},child={},sibling={},rows:any[]=[];bindScopeParent(child,owner)
let scoped:any
await ctx.plugin({inject:['mcpResources','tools'],apply(inner:any){scoped=createScope(inner,owner)}})
function provider(label:string){return {request:async(request:any)=>({label,request,contents:[{blob:'YWJj',uri:'doc://a',text:'text'}],nested:{blob:'\ud83d\ude00'}})}}
async function snapshot(name:string){
 const observations=[]
 for(const [who,agent] of [['global',undefined],['owner',owner],['child',child],['sibling',sibling]] as const){
  const prompt=await ctx.systemPrompt.assemble(agent===undefined?{}:{scope:agent})
  observations.push({who,tools:ctx.tools.schemas(agent).sort((a:any,b:any)=>a.name.localeCompare(b.name)),prompt:prompt.sections.filter((row:any)=>row.name==='mcp-resource-servers').map((row:any)=>row.text)})
 }
 rows.push({name,observations})
}
try{
 await snapshot('empty')
 const first=ctx.mcpResources.register('docs',provider('global')),second=ctx.mcpResources.register('second',provider('second'))
 const local=scoped.ctx.mcpResources.register('docs',provider('local'))
 await snapshot('global-and-local')
 try{scoped.ctx.mcpResources.register('docs',provider('duplicate'))}catch(error){rows.push({name:'duplicate',error:(error as Error).message})}
 for(const [name,agent,server] of [['global',undefined,'docs'],['owner',owner,'docs'],['child',child,'docs'],['sibling',sibling,'docs'],['missing',owner,'missing']] as const){
  try{const value=await (ctx.mcpResources as any).request(server,{method:'resources/list',cursor:''},{agent,signal:new AbortController().signal});rows.push({name,value,content:renderResourceResult(server,value)})}
  catch(error){rows.push({name,error:(error as Error).message})}
 }
 first();await snapshot('global-docs-removed')
 local();await snapshot('local-docs-removed')
 second();await snapshot('all-removed')
 await scoped.dispose()
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
