import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:SystemPrompt}=await load('packages/core/system-prompt/src/index.ts'),{default:Tools}=await load('packages/core/tools/src/index.ts'),{ToolExecutionPipeline}=await load('packages/core/tools/src/pipeline.ts'),rows:any[]=[]
for(const action of ['enabled','disabled','once','closed','foreign','removed','replace','reject','abort-before','abort-after','abort-reject','dispatch']){
 const ctx=new Context();await ctx.plugin(SystemPrompt);await ctx.plugin(Tools)
 const tools=ctx.tools,agent={},foreign={},controller=new AbortController(),reason=new Error('cancelled'),failure=new Error('condition failed'),trace:any[]=[],bodies:boolean[]=[],model={provider:'p',model:'m',reasoningEffort:'high'},context={agent,modelSelection:model,signal:controller.signal},row:any={action};let selection:any
 const condition=async(value:any)=>{trace.push({agent:value.agent===agent,model:value.modelSelection===model,signal:value.signal===controller.signal});await Promise.resolve();if(['abort-after','abort-reject'].includes(action))controller.abort(reason);if(['reject','abort-reject'].includes(action))throw failure;if(['removed','replace'].includes(action))dispose();if(action==='replace')tools.register(definition,{when:condition});return action!=='disabled'}
 const definition={name:'echo',description:'echo',parameters:{type:'object'},output:{schema:{type:'string'},render:(_:any,value:string)=>[{type:'text',text:value}]},async execute(_:any,execution:any){bodies.push(execution.toolSet===selection);return 'ok'}},dispose=tools.register(definition,{when:condition});tools.register({...definition,name:'plain'})
 row.inspect=tools.definitions(agent).map((item:any)=>item.name);row.outside=tools.executable('echo',agent)!==undefined
 if(action==='abort-before')controller.abort(reason)
 try{selection=await tools.resolve(context);if(action==='once')controller.abort(reason);if(action==='closed'){selection.dispose();selection.dispose()}const scope=action==='foreign'?foreign:agent;row.admitted=tools.definitions(scope,selection).map((item:any)=>item.name);row.schemas=tools.schemas(scope,selection).map((item:any)=>item.name);row.executable=tools.executable('echo',scope,selection)!==undefined
  if(action==='dispatch'){const pipeline=new ToolExecutionPipeline(ctx),execute=async(input:any)=>{const prepared=await pipeline.prepare(input);const outcome=prepared.kind==='dispatch'?await pipeline.dispatch(prepared.exec):prepared;return pipeline.complete(prepared.exec,outcome)},input={name:'echo',arguments:{},agent,signal:controller.signal},a=await execute({...input,callId:'a'}),b=await execute({...input,callId:'b',toolSet:selection});selection.dispose();const c=await execute({...input,callId:'c',toolSet:selection});row.results=[a,b,c].map(result=>result.isError?result.error.info.code:result.value);row.bodies=bodies}
  selection.dispose();row.disposed=selection.view(agent).size
 }catch(error:any){row.error={name:error.name,message:error.message,code:error.code??null,cause:error.cause===failure,reason:error===reason}}
 row.conditions=trace;rows.push(row);await ctx.fiber.dispose()
}
const {createScope}=await load('packages/core/scope/src/index.ts')
for(const action of ['scoped-shadow','late-restriction','scoped-unload']){
 const ctx=new Context();await ctx.plugin(SystemPrompt);await ctx.plugin(Tools);let owner:any;await ctx.plugin(Object.assign((scope:any)=>{owner=scope},{inject:['tools']}));const tools=ctx.tools,agent:any={},scope=createScope(owner,agent),controller=new AbortController();agent.ctx=scope.ctx
 const definition={name:'echo',description:'global',parameters:{type:'object'},output:{schema:{type:'string'},render:()=>[]},async execute(){return 'ok'}};tools.register(definition)
 if(action!=='late-restriction')scope.ctx.tools.register({...definition,description:'scoped'},{when:()=>action!=='scoped-shadow'})
 const selection=await tools.resolve({agent,modelSelection:{},signal:controller.signal}),read=()=>tools.definitions(agent,selection).map((item:any)=>item.description),row:any={action,before:read()};let lift:any
 if(action==='late-restriction')lift=scope.ctx.tools.restrict({deny:['echo']});else if(action==='scoped-unload')await scope.dispose()
 row.after=read();if(lift){lift();row.restored=read()}selection.dispose();rows.push(row);await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(rows))
