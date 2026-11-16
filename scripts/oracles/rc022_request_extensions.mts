import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {prepareRequestExtensions}=await load('packages/llm/llm-deepseek/src/request-extensions.ts')
const {errorChain}=await load('packages/llm/llm/src/error.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],original=JSON.stringify
for(const [index,entry] of input.entries()){
 const mode=entry.mode,events:any[]=[],requests:any[]=[],serial:any[]=[]
 const body={model:'m',messages:[{role:'user',content:[{type:'text',text:'hello'}]}]}
 const prepare=async(request:any)=>{
  requests.push({bodySame:request.body===body,sessionId:request.sessionId,purpose:request.purpose})
  if(mode==='prepare-error')throw new Error('prepare unavailable',{cause:new Error('inner failure')})
  return {fields:entry.fields,async accept(){events.push('accepted');if(['accept-error','accept-reporter-error'].includes(mode))throw new Error('commit unavailable')}}
 }
 JSON.stringify=((value:any,...args:any[])=>{
  if(value&&typeof value==='object'&&Object.hasOwn(value,'messages')){
   serial.push(Object.keys(value))
   if(mode==='base-overflow'||['merged-overflow','omit-reporter-error'].includes(mode)&&Object.keys(entry.fields).some(key=>Object.hasOwn(value,key)))throw new Error('synthetic serialization overflow')
  }
  return (original as any)(value,...args)
 }) as any
 const omitted=(fields:any,error:any)=>{events.push({omitted:fields,error:errorChain(error)});if(mode==='omit-reporter-error')throw new Error('omission reporter failed')}
 const unaccepted=(error:any)=>{events.push({unaccepted:errorChain(error)});if(mode==='accept-reporter-error')throw new Error('acceptance reporter failed')}
 let result:any
 try{
  const prepared=await prepareRequestExtensions(body,{sessionId:'s',purpose:'compaction'},prepare,omitted,unaccepted)
  result={payload:prepared.payload,beforeAcceptance:[...events]}
  try{await prepared.accept();result.acceptance='fulfilled'}catch(error){result.acceptanceError=errorChain(error)}
 }catch(error:any){result={error:errorChain(error),code:error.code??null}}
 finally{JSON.stringify=original}
 rows.push({index,requests,serial,events,...result})
}
const {Context}=await load('vendor/cordis/src/index.ts')
const {default:Registry}=await load('packages/llm/deepseek-llm-api-extensions/src/index.ts')
const ctx=new Context(),commits:any[]=[],warnings:any[]=[];let failing=true;const mutable={value:0}
try{
 await ctx.plugin(Registry)
 ctx.logger.exporter({levels:{default:2},export(message:any){if(message.type==='warn')warnings.push({format:message.args[0],error:errorChain(message.args[1])})}})
 const registry=ctx.deepseekLlmApiExtensions as any
 const bad=()=>{if(failing)throw new Error('prepare unavailable');return {value:['recovered']}}
 let undo=registry.register('inventory_bad',{prepare:bad})
 registry.register('inventory_good',{prepare:()=>({value:mutable,accept:()=>{commits.push(true)}})})
 for(let round=0;round<5;round++){
  if(round===2){await undo();undo=registry.register('inventory_bad',{prepare:bad})}
  failing=round!==3;mutable.value=round
  const request=await prepareRequestExtensions({model:'m'},{signal:new AbortController().signal},value=>registry.prepare(value),()=>{},()=>{})
  mutable.value=99;await request.accept();await request.accept()
  rows.push({kind:'registry',round,payload:request.payload,commits:commits.length,warnings:structuredClone(warnings)})
 }
 for(const [field,message] of [['fail_one','first commit'],['fail_two','second commit']])registry.register(field,{prepare:()=>({value:true,accept:()=>{throw new Error(message)}})})
 const unaccepted:string[]=[]
 const request=await prepareRequestExtensions({model:'m'},{signal:new AbortController().signal},value=>registry.prepare(value),()=>{},error=>unaccepted.push(errorChain(error)))
 await request.accept();await request.accept()
 rows.push({kind:'aggregate',unaccepted,commits:commits.length})
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
