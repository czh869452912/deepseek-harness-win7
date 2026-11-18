import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const source=process.argv[2]!
const load=(path:string)=>import(pathToFileURL(resolve(source,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts')
const {default:SessionStore,Session}=await load('packages/core/session/src/index.ts')
const {default:SessionProjectionRegistry}=await load('packages/session/session-projection/src/index.ts')
const {AgentModel,modelSelectionProjectionDefinition}=await load('packages/core/agent/src/index.ts')
const {AcpModelControl}=await load('packages/acp/acp/src/model-control.ts')
const {toolResultUpdate}=await load('packages/acp/acp/src/updates.ts')
const rows:any[]=[]
for(const defaultEffort of [undefined,'high']){
 const ctx=new Context()
 try{
  await ctx.plugin(SessionStore);await ctx.plugin(SessionProjectionRegistry)
  const projection=await ctx.sessionProjections.register(modelSelectionProjectionDefinition)
  const session=ctx.sessions.create('acp-model'),model=new AgentModel(projection.readerFor(session),session,{provider:'mock',model:'first'})
  const runtime={listProviders:()=>[{id:'mock',name:'Mock'},{id:'other',name:'Other'}],
   listModels:async()=>[{id:'first',name:'First'},{id:'next',name:'Next'}],
   resolveModelInfo:async()=>({reasoning:{efforts:[{id:'low',name:'Low'},{id:'high',name:'High'}],...defaultEffort===undefined?{}:{defaultEffort}}}),
   resolveCallConfig:async(selection:any)=>({...selection,...selection.reasoningEffort===undefined&&defaultEffort!==undefined?{reasoningEffort:defaultEffort}:{}})}
  const control=new AcpModelControl(runtime as any,model)
  const row:any={default:defaultEffort??null,initial:await control.options()}
  row.switched=await control.set('model','["other","next"]');row.effort=await control.set('reasoning_effort','low')
  row.reset=await control.set('reasoning_effort',defaultEffort===undefined?'':'high')
  row.errors=[]
  for(const [key,value] of [['model',false],['model','missing'],['reasoning_effort','extreme']] as const){
   try{await control.set(key,value)}catch(error:any){row.errors.push(error.message)}
  }
  row.selected=model.current();const events=session.snapshotEvents();row.selections=events.map((event:any)=>event.data)
  const restored=Session.create('restored',events);row.restored=new AgentModel(projection.readerFor(restored),restored,{}).current()
  rows.push(row)
 }finally{await ctx.fiber.dispose()}
}
const ctx={get:(name:string)=>name==='attachments'?{readImage:async(ref:any)=>({ref,data:Buffer.from('image')})}:undefined}
for(const isError of [false,true]){
 const message={toolCallId:'echo',isError,content:[{type:'text',text:'result'},{type:'image',attachment:{mediaType:'image/png'}}]}
 rows.push({update:await toolResultUpdate(ctx as any,{data:{message}} as any)})
}
process.stdout.write(JSON.stringify(rows))
