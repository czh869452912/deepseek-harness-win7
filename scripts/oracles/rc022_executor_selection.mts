import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{createScope}=await load('packages/core/scope/src/index.ts'),{default:SystemPrompt}=await load('packages/core/system-prompt/src/index.ts'),{default:Tools}=await load('packages/core/tools/src/index.ts'),rows:any[]=[]
for(const action of ['missing','duplicate','root-unload','scoped-unload','scoped-replace','inherited','accepted','sections']){
 const ctx=new Context();await ctx.plugin(SystemPrompt);await ctx.plugin(Tools);const tools=ctx.tools;let owner:any
 const rootOwner=await ctx.plugin(Object.assign((scope:any)=>{owner=scope},{inject:['tools','systemPrompt']})),agent:any={},child:any={},scope=createScope(owner,agent),childScope=createScope(owner,child,{parent:agent});agent.ctx=scope.ctx;child.ctx=childScope.ctx
 let release:any,start:any,accepted:any;const gate=new Promise<void>(resolve=>release=resolve),started=new Promise<void>(resolve=>start=resolve),request={calls:[],agent,signal:new AbortController().signal},row:any={action}
 class Executor{sections:any[];constructor(public name:string){this.sections=[{name:'fixture-'+name,order:123,text:(definitions:any[])=>name+':'+definitions.map(item=>item.name).join(',')}]}describe(){return {schemas:[{name:this.name,description:'',parameters:{type:'object'}}]}}async execute(input:any){start();if(action==='accepted')await gate;return {provider:this.name,same:input===request}}}
 const dispatch=async(target=agent)=>{try{return await tools.execute(target===agent?request:{...request,agent:target})}catch(error:any){return {code:error.code}}}
 try{
  if(action!=='missing')owner.tools.setExecutor(new Executor('root'))
  if(action==='duplicate')try{tools.setExecutor(new Executor('duplicate'))}catch(error:any){row.duplicate=error.message}
  if(['scoped-unload','scoped-replace','inherited','sections'].includes(action))scope.ctx.tools.setExecutor(new Executor('local'))
  if(action==='accepted'){accepted=dispatch();await started;await rootOwner.dispose();row.during=await dispatch();release();row.accepted=await accepted}
  else if(action==='root-unload')await rootOwner.dispose()
  else if(['scoped-unload','scoped-replace'].includes(action)){await scope.dispose();row.unloaded=await dispatch();if(action==='scoped-replace'){const replacement=createScope(owner,agent);agent.ctx=replacement.ctx;replacement.ctx.tools.setExecutor(new Executor('replacement'))}}
  row.dispatch=await dispatch(action==='inherited'?child:agent)
  if(action==='sections'){const assembly=await ctx.systemPrompt.assemble({scope:agent});row.sections=assembly.sections.filter((item:any)=>item.name.startsWith('fixture-')).map((item:any)=>({name:item.name,text:item.text}));row.schemas=assembly.tools.map((item:any)=>item.name)}rows.push(row)
 }finally{release();if(accepted)await accepted.catch(()=>{});await ctx.fiber.dispose()}
}
for(const action of ['register-rollback','register-nesting']){
 const ctx=new Context();await ctx.plugin(SystemPrompt);await ctx.plugin(Tools);const tools=ctx.tools,row:any={action},trace:any[]=[],definition={name:'echo',description:'',parameters:{type:'object'},output:{schema:{type:'string'},render:()=>[]},async execute(){return 'ok'}}
 if(action==='register-rollback'){let failed=false;const remove=ctx.on('tools/change',()=>{if(!failed){failed=true;throw new Error('change failed')}});try{tools.register(definition)}catch(error:any){row.error=error.message}row.leaked=tools.get('echo')!==undefined;remove();const dispose=tools.register(definition);row.retry=tools.get('echo')!==undefined;dispose()}
 else{const owner=await ctx.plugin(Object.assign((scope:any)=>{scope.effect(function*(){yield()=>trace.push('last');yield scope.tools.register(definition);yield async()=>{await Promise.resolve();trace.push(scope.tools.get('echo')!==undefined)}})},{inject:['tools']}));await owner.dispose();row.trace=trace;row.remaining=tools.get('echo')!==undefined}
 rows.push(row);await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(rows))
