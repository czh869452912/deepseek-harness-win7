import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:SystemPrompt}=await load('packages/core/system-prompt/src/index.ts'),{default:Tools}=await load('packages/core/tools/src/index.ts'),{ToolExecutionPipeline}=await load('packages/core/tools/src/pipeline.ts'),rows:any[]=[]
for(const action of ['project','replace','project-fails','body-fails','pre-fails','post-fails','final-fails','guard-info','deny-info','cancel','arguments','nested-meta','unload']){
 const ctx=new Context();await ctx.plugin(SystemPrompt);await ctx.plugin(Tools)
 const controller=new AbortController(),trace:string[]=[],observed:any[]=[],row:any={action},text=(value:string)=>[{type:'text',text:value}]
 const definition={name:'echo',description:'echo',parameters:{type:'object'},output:{schema:{type:'string'},render:()=>text('fallback'),presentationMeta:(_:any,v:any)=>({shown:v})},execute(args:any){trace.push('body');if(action==='body-fails')throw new Error('body failed');return args.value},projectContent(){trace.push('project');if(action==='project-fails')throw new Error('projection failed');return text('prepared')},finalizeContent(_:any,result:any){trace.push('final');if(action==='final-fails')throw new Error('finalization failed');return text('final:'+result.content[0].text)}}
 const dispose=ctx.tools.register(definition)
 ctx.on('tools/pre-execute',async(_:any,next:any)=>{trace.push('pre');definition.projectContent=()=>text('late');if(action==='pre-fails')throw new Error('pre failed');if(action==='unload')dispose();if(action==='deny-info')return {kind:'deny',reason:'blocked',info:{name:'PolicyError',code:'POLICY',reason:'raw'}};if(action==='cancel')return {kind:'cancel'};if(action==='arguments')return {kind:'allow',arguments:{value:'rewritten'}};return next()})
 ctx.on('tools/post-execute',async(_:any,result:any)=>{trace.push('post:'+result.content[0].text);if(action==='post-fails')throw new Error('post failed');return {kind:'accept',...action==='replace'?{content:text('policy')}:{}}})
 ctx.on('tools/result',(execution:any,result:any)=>{trace.push('result');observed.push(result);row.executionFrozen=Object.isFrozen(execution)})
 if(action==='guard-info')ctx.tools.guard(()=>({reason:'guarded',info:{name:'GuardError',code:'GUARD',reason:'raw'}}))
 const pipeline=new ToolExecutionPipeline(ctx),prepared=await pipeline.prepare({callId:'call',name:'echo',arguments:{value:'original'},signal:controller.signal,...action==='nested-meta'?{parent:{}}:{}}),outcome=prepared.kind==='dispatch'?await pipeline.dispatch(prepared.exec):prepared,result=await pipeline.complete(prepared.exec,outcome)
 Object.assign(row,{trace,content:result.content,error:result.isError?result.error:null,value:result.isError?null:result.value,meta:result.meta??null,exactResult:observed.length===1&&observed[0]===result,schemaPrivate:action==='unload'||!['projectContent','finalizeContent'].some(k=>k in ctx.tools.schemas()[0])});rows.push(row);await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(rows))
