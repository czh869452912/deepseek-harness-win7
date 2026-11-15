import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href),{Context}=await load('vendor/cordis/src/index.ts'),{default:Store}=await load('packages/core/session/src/index.ts'),{default:Projections}=await load('packages/session/session-projection/src/index.ts'),{default:Runtime}=await load('packages/subagent/subagent/src/index.ts'),rows:any[]=[]
for(const action of ['local','external','no-provider','no-methods','duplicate','added-failure','removed','provider-change','reserved-external','capability','fork-preset','stale-parent','invalid-depth','invalid-schema','no-agents']){
 const ctx=new Context();await ctx.plugin(Store);await ctx.plugin(Projections);ctx.provide('workingDirectory');ctx.workingDirectory={};const parent={id:'parent'},trace:string[]=[]
 if(action!=='no-agents'){ctx.provide('agents');ctx.agents={get:(id:string)=>id==='parent'?parent:undefined,list:()=>[]}}
 ctx.on('subagent/provider-added',(provider:any)=>trace.push('added:'+provider.name));ctx.on('subagent/provider-removed',(name:string)=>trace.push('removed:'+name))
 const owner=await ctx.plugin(Runtime),service=ctx.subagents,original=service['manager'],session=ctx.sessions.create('session'),row:any={action,depth:service.resolveMaxDepth(),capacity:service['config'].maxActiveSubagents.get(),managed:service.resolveMaxDepth('provider-managed')===undefined,projections:Object.keys(ctx.sessionProjections.snapshot(session).values).sort()}
 const prepare=async()=>{trace.push('prepared');return {}},external=async()=>{trace.push('started');return {}},provider:any={name:'test',capabilities:{agentOptions:true,agentPreset:true,outputSchema:true,depthLimit:true},inheritsParentContext:false}
 if(['external','reserved-external'].includes(action))provider.start=external;else if(action!=='no-methods')provider.prepareContinuable=prepare
 const spec:any={provider:'test',parent,prompt:[],label:'Task',signal:new AbortController().signal,delivery:'caller'};let dispose:any
 try{
  if(action==='added-failure')ctx.on('subagent/provider-added',()=>{throw Error('listener failure')})
  if(action!=='no-provider')dispose=service.registerProvider(provider)
  if(action==='duplicate')service.registerProvider(provider);else if(action==='removed'){dispose();dispose()}
  else if(action==='reserved-external')spec.childId='reserved';else if(action==='capability'){provider.capabilities.agentOptions=false;spec.agentOptions={}}
  else if(action==='fork-preset'){provider.inheritsParentContext=true;spec.agentPreset='coding'}else if(action==='stale-parent')spec.parent={id:'parent'}
  else if(action==='invalid-depth')spec.maxDepth=-1;else if(action==='invalid-schema')spec.outputSchema={type:'array',items:{type:'string'}}
  if(action!=='no-agents')service['manager']={startLocal:async(_spec:any,checked:any)=>{trace.push('local');if(action==='provider-change'){dispose();service.registerProvider({name:'test',capabilities:{},prepareContinuable:prepare})}await checked({});return {kind:'local'}},startExternal:async(_spec:any,checked:any)=>{trace.push('external');await checked({});return {kind:'external'}}}
  row.value=await service.startActivation(spec)
 }catch(error:any){row.error=error.code??null}
 finally{service['manager']=original;row.registered=service.getProvider('test')!==undefined;await owner.dispose();row.released=ctx.get('subagents')===undefined;row.remaining=Object.keys(ctx.sessionProjections.snapshot(session).values).sort();row.trace=trace;await ctx.fiber.dispose()}
 rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
