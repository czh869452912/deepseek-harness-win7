import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {default:Sessions}=await load('packages/core/session/src/index.ts')
const {default:Extensions}=await load('packages/llm/deepseek-llm-api-extensions/src/index.ts')
const Upload=await load('packages/session/session-log-deepseek/src/index.ts')
const cases=['default','disabled','toggle','exclude','purpose','throw','blocked','exact','below','prefix','unload','owner']
const rows:any[]=[],original=Date.now;Date.now=()=>1000
try{for(const name of cases){
 const ctx=new Context(),warnings:string[]=[],uploads:any[]=[],results:any[]=[]
 ctx.logger.warn=(text:string)=>warnings.push(String(text))
 await ctx.plugin(Sessions);await ctx.plugin(Extensions)
 const session=ctx.sessions.create('upload')
 for(let index=0;index<2;index++)session.append('user/message',{id:'message-'+index,role:'user',source:{kind:'user'},content:[{type:'text',text:'文旦🍐'}]},{surfaceOp:'append'})
 const first={version:1,sessionFormatVersion:4,session:{version:4,id:'upload',createdAt:1000},afterSeq:-1,throughSeq:0,events:[session.snapshotEvents()[0]]}
 const limit=Buffer.byteLength(JSON.stringify(first)),config:any={}
 if(['disabled','toggle'].includes(name))config.enabled=false
 if(name==='blocked')config.maxBytes=1
 if(['exact','prefix'].includes(name))config.maxBytes=limit
 if(name==='below')config.maxBytes=limit-1
 const fiber=await ctx.plugin(Upload,config),service=ctx.sessionLogDeepSeek
 const disposer=['exclude','purpose','throw'].includes(name)?service.registerExclusion((upload:any)=>{
  uploads.push(structuredClone(upload));if(name==='throw')throw Error('controlled exclusion')
  return name==='exclude'||upload.purpose==='title'
 }):undefined
 const owner=name==='owner'?await ctx.plugin(Object.assign((child:any)=>{child.sessionLogDeepSeek.registerExclusion((upload:any)=>{uploads.push(structuredClone(upload));return true})},{inject:['sessionLogDeepSeek']})):undefined
 const prepare=async(purpose?:string)=>{const prepared=await ctx.deepseekLlmApiExtensions.prepare({sessionId:'upload',body:{},signal:new AbortController().signal,...(purpose===undefined?{}:{purpose})});results.push(structuredClone(prepared.fields));return prepared}
 try{
  const prepared=await prepare(name==='purpose'?'title':undefined)
  if(name==='prefix')await prepared.accept()
  if(name==='toggle')await fiber.update({enabled:true})
  if(disposer)await disposer()
  if(owner)await owner.dispose()
  if(name==='unload')await fiber.dispose()
  await prepare()
  rows.push({case:name,results,uploads,warnings,events:session.snapshotEvents(),mounted:ctx.get('sessionLogDeepSeek',false)!==undefined})
 }finally{await ctx.fiber.dispose()}
}}finally{Date.now=original}
process.stdout.write(JSON.stringify(rows))
