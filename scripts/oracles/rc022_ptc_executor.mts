import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Prompt}=await load('packages/core/system-prompt/src/index.ts'),{default:Tools}=await load('packages/core/tools/src/index.ts'),{PtcExecutor}=await load('packages/core/tool-executor-ptc/src/index.ts'),{PtcRuntime}=await load('packages/ptc-runtime/ptc-runtime/src/index.ts'),rows:any[]=[]
for(const action of ['missing','unknown-language','python-schema','typescript-schema','repl-schema','controls-schema','standalone','agent','direct','nested-error','admission','no-directory','description','timeout-unavailable','timeout-invalid','escalation-unavailable','policy-missing','program-error','runtime-timeout','caller-abort','retained-abort','limit','reset-unsupported','reset','reset-fails','release-once','null']){
 const ctx=new Context();await ctx.plugin(Prompt);await ctx.plugin(Tools)
 const events:any[]=[],notices:string[]=[],releases:boolean[]=[],runs:any[]=[],bodies:any[]=[],controller=new AbortController(),row:any={action},agent:any={ctx,session:{id:'session',append(type:string,data:any){events.push({type,data:JSON.parse(JSON.stringify(data))})}},inject(message:any){notices.push(message.content[0].text)}}
 const cwd=process.cwd()
 if(action!=='no-directory'){ctx.provide('workingDirectory');ctx.set('workingDirectory',{ensure:async()=>cwd})}
 class Runtime extends PtcRuntime{
  language=['typescript-schema','repl-schema'].includes(action)?'typescript':action==='unknown-language'?'unknown':'python';isolation='fake'
  get programFormat(){return action==='repl-schema'?'repl':'function-body'}get retainsState(){return ['retained-abort','reset','reset-fails'].includes(action)}get sandboxMode(){return ['controls-schema','policy-missing'].includes(action)?'read-only':undefined}get timeout(){return action==='timeout-unavailable'?undefined:{defaultMs:120000,maxMs:600000}}get executionInstructions(){return 'Provider instructions.'}
  resolve(request:any){return {...request,cwd:request.cwd??cwd,timeoutMs:action==='limit'?1000:request.timeoutMs??120000}}
  async run(spec:any){const functions=spec.bindings[0].functions;runs.push({program:spec.program,names:Object.keys(functions).sort(),cwd:spec.cwd,timeout:spec.timeoutMs,stateOwner:spec.stateOwner===agent,hasOwner:spec.stateOwner!==undefined});if(['caller-abort','retained-abort'].includes(action)){controller.abort(new Error('caller canceled'));return {logs:[],error:{kind:'abort',message:'worker canceled'}}}if(['program-error','runtime-timeout'].includes(action))return {logs:['captured'],error:{kind:action==='runtime-timeout'?'timeout':'exception',message:'program failed'}};if(action==='null')return {logs:[],value:null};let value;try{value=await functions.work({n:3})}catch(error:any){if(action==='limit')return {logs:[],error:{kind:'abort',message:'worker canceled'}};value=error.message}return {logs:['log'],value}}
  async release(owner:any){releases.push(owner===agent);if(action==='reset-fails')throw new Error('release failed')}
 }
 if(action!=='missing')await ctx.plugin(Runtime)
 ctx.tools.register({name:'work',description:'Read work',parameters:{type:'object',properties:{n:{type:'integer'}},required:['n']},execute(args:any,execution:any){bodies.push({schema:execution.schema.name,parent:execution.parent!==undefined,admitted:execution.toolSet!==undefined,n:args.n});if(action==='nested-error')throw new Error('nested failed');return {n:args.n*2}},output:{schema:{type:'object',properties:{n:{type:'integer'}},required:['n']},render:(_:any,v:any)=>[{type:'text',text:String(v.n)}]}})
 const executor=new PtcExecutor(ctx,action==='limit'?{maxSubCallsPerMinute:1}:{});ctx.tools.setExecutor(executor);let selection:any
 try{
  if(['missing','unknown-language'].includes(action)||action.endsWith('schema')){try{row.model=executor.describe(ctx.tools.definitions());row.sdk=executor['renderSdk'](ctx.tools.definitions());row.sections=executor.sections.map((s:any)=>({name:s.name,order:s.order,interpolate:s.interpolate}))}catch(error:any){row.error=error.message}}
  else if(action.startsWith('reset')){try{await executor.reset(agent);row.reset='done'}catch(error:any){row.reset={message:error.message,code:error.code}}}
  else{
   if(action==='admission')selection=await ctx.tools.resolve({agent,modelSelection:{},signal:controller.signal})
   const args:any={code:'fixture',description:'Run fixture'};if(action==='description')args.description='  ';if(['timeout-unavailable','timeout-invalid'].includes(action))args.timeoutMs=action==='timeout-unavailable'?20:0;if(action==='escalation-unavailable')Object.assign(args,{sandbox_permissions:'danger-full-access',justification:'Need access'})
   const input:any={calls:[{type:'tool-call',id:'outer',name:action==='direct'?'work':'run_code',arguments:JSON.stringify(action==='direct'?{n:1}:args)}],signal:controller.signal};if(action!=='standalone')input.agent=agent;if(selection)input.toolSet=selection
   row.results=[];for(let n=0;n<(action==='release-once'?2:1);n++){const batch=await ctx.tools.execute(input),result=batch.results[0].result;row.results.push({isError:result.isError,error:result.error??null,content:result.content,value:result.isError?null:result.value})}
  }
  Object.assign(row,{bodies,runs,events,notices})
 }finally{selection?.dispose();await ctx.fiber.dispose()}
 row.releases=releases;rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
