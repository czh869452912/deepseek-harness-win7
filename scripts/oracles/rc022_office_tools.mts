import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
const [source, corpus] = process.argv.slice(2)
const {apply,Config}=await import(pathToFileURL(path.join(source,'packages/document/tool-office/src/index.ts')))
const {OfficeKitError}=await import(pathToFileURL(path.join(source,'packages/document/office-kit/src/index.ts')))
const {SubagentError}=await import(pathToFileURL(path.join(source,'packages/subagent/subagent/src/index.ts')))
const rows:any[]=[]
for(const name of JSON.parse(fs.readFileSync(corpus,'utf8'))){
 const calls:any[]=[],definitions:any[]=[],conditions:any[]=[],events=new Map();let count=0
 const session:any={id:'session',requestHeader:()=>({config:name==='routed'?{provider:'route',model:'vision'}:{},tools:name==='header'?[{name:'office_convert'}]:[]})},agent:any={session,options:{provider:'base',model:'base-model'}},signal=new AbortController().signal
 const kind=name==='recalculate'?'recalculate':['convert','remote','owner-error','no-owner','invalid-format'].includes(name)?'convert':'render'
 const operation=async(request:any,signal:any)=>{
  const {source,...rest}=request,{read,...metadata}=source;calls.push({request:rest,source:metadata});const value=await read(signal,20);calls.push({sourceBytes:[...value.bytes],version:value.version})
  if(['busy','unavailable'].includes(name))throw new OfficeKitError(name,'engine failure')
  return kind==='render'?{images:[{png:new Uint8Array(name==='oversized'?11:8),page:1}],pageCount:1,dpi:96,missingFonts:['Font']}:{path:'C:/store/output.txt',bytes:4,pageCount:2,missingFonts:[]}
 }
 const ctx:any={on:(key:string,callback:any)=>events.set(key,callback),get:(key:string)=>ctx[key],tools:{register:(definition:any,options:any)=>{definitions.push(definition);conditions.push(options.when)}},agents:{get:()=>agent},workingDirectory:{ensure:async()=>{calls.push('directory');return 'C:/working'}},fs:{resolve:async(path:any,options:any)=>{calls.push({resolve:path,cwd:options.cwd});return {displayPath:'C:/display/report.docx'}},stat:async()=>{calls.push('stat');count++;return name==='missing'?undefined:{type:name==='directory'?'directory':'file',version:name==='changed'&&count>1?'v2':'v1',size:4}},readByteRange:async(_target:any,options:any)=>{calls.push({range:options});return new Uint8Array([80])},readBytes:async(_target:any,_signal:any,maximum:any)=>{calls.push({read:maximum});if(name==='too-large')throw Object.assign(Error('large'),{code:'FS_TOO_LARGE'});return new Uint8Array([80,75,49,50])},processPath:()=> 'C:/canonical/report.docx',processPathFromHostPath:(p:any)=>name==='remote'?undefined:p}}
 if(name!=='no-kit')ctx.officeKit={outputDirectory:'C:/store',renderImages:operation,convertTo:operation,recalculate:operation}
 if(name!=='no-llm')ctx.llm={resolveModelInfo:async(provider:any,model:any)=>{calls.push({route:[provider,model]});return {inputModalities:name==='text-model'?['text']:['image']}}}
 if(name!=='no-store')ctx.attachments={imageLimits:{maxImagesPerMessage:3,maxImagePixels:100,maxImageDimension:10,maxMessageImageBytes:50,maxImageBytes:10},saveImages:async(inputs:any[])=>{calls.push({save:inputs.map(x=>({name:x.name,mediaType:x.mediaType,bytes:x.data.length}))});return [{attachmentId:'ref',mediaType:name==='gif'?'image/gif':name==='scaled'?'image/webp':'image/png',bytes:8,width:2,height:3,...name==='scaled'?{originalDimensions:{width:4,height:6}}:{}}]},isAttachmentError:()=>false}
 if(name!=='no-owner')ctx.subagents={rootOf:()=>{calls.push('owner');if(name==='owner-error')throw new SubagentError('not owned','UNAUTHORIZED');return {session:{id:'root'}}}}
 apply(ctx,Config({}));const definition=definitions.find(x=>x.name==='office_'+kind),when=conditions[0],before=when({agent})
 if(['message','stale-message'].includes(name))events.get('session/event')(name==='message'?session:{id:'session'},{type:'user/message',data:{source:{kind:'skill-invocation',name:'office'}}})
 else events.get('tools/result')({agent,name:'skill',arguments:{name:name==='invalid-skill'?[]:name==='wrong-skill'?'other':'office'}},{isError:name==='failed-skill'})
 const after=when({agent}),args:any={input:kind==='recalculate'?'book.xlsx':'report.docx'}
 if(kind!=='render')args.format=name==='invalid-format'?'csv':kind==='recalculate'?'xlsx':'txt'
 if(name==='invalid-page')args.pages=[0]
 if(name==='unknown')args.unknown=true
 let result:any
 try{const value=await definition.execute(args,{agent:name==='no-agent'?undefined:agent,signal});result={value,content:definition.output.render(args,value),meta:definition.output.presentationMeta(args,value)}}catch(error:any){result={error:{message:error.message,code:error.code??null}}}
 events.get('agent/disposed')({agent});rows.push({name,before,after,disposed:when({agent}),result,calls,present:definition.presentCall(args),concurrent:definition.isConcurrencySafe(args)})
}
console.log(JSON.stringify(rows))
