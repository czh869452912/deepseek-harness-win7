import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {deepSeekImageTokens,deepSeekRequestImageDimensions}=await load('packages/llm/llm-deepseek/src/image-tokens.ts')
const {resolveRequestImageTarget}=await load('packages/llm/llm-deepseek/src/request-pricing.ts')
const {imagePricing,prepareImages,inlineImages,prepareFileIds}=await load('packages/llm/llm-deepseek/src/images.ts')
const {requiredImageOffload}=await load('packages/llm/llm/src/content.ts')
const {resolveAdapterOptions}=await load('packages/llm/llm-deepseek/src/config.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [index,[width,height]] of input.geometry.entries()){
 let result:any
 try{result={tokens:deepSeekImageTokens(width,height),dimensions:deepSeekRequestImageDimensions(width,height),target:resolveRequestImageTarget({}, {width,height})}}
 catch(error:any){result={error:error.message}}
 rows.push({kind:'geometry',index,...result})
}
for(const [index,entry] of input.pricing.entries()){
 const value=imagePricing({models:[entry.model,{id:'text'}]},entry.id,()=>entry.access??undefined).priceImages(entry.images)
 rows.push({kind:'pricing',index,value})
}
for(const [index,entry] of input.admission.entries()){
 const content=entry.lengths.map((bytes:number)=>({type:'image',attachment:{bytes}}))
 const count=requiredImageOffload([{content}],entry.budget,(block:any)=>block.attachment.bytes)
 rows.push({kind:'admission',index,count})
}
for(const [index,entry] of input.preparation.entries()){
 const calls:any[]=[],occurrences:any[]=[],history=structuredClone(entry.history),before=JSON.stringify(history)
 const attachments={async readImageRequest(ref:any,target:any){calls.push({ref,target});return {attachment:ref,bytes:ref.attachmentId[7]==='a'?3:12,width:target.width,height:target.height}}}
 const files={async resolve(version:any,location:any){occurrences.push({id:version.attachment.attachmentId,location});return 'file-'+occurrences.length}}
 let result:any
 try{
  const config=resolveAdapterOptions(entry.config)
  const value=await prepareImages(history,config,entry.model,entry.attachments?attachments:undefined,()=>entry.access??undefined,new AbortController().signal)
  const ids=await prepareFileIds(value.messages,value.versions,files)
  result={messages:value.messages,versions:Object.fromEntries(value.versions),ids:Object.fromEntries(ids)}
  try{result.inline=inlineImages(value.messages,value.versions,config)}catch(error:any){result.inlineError=error.failure}
 }catch(error:any){result={error:error.message,code:error.code??null,failure:error.failure??null}}
 rows.push({kind:'preparation',index,calls,occurrences,unchanged:JSON.stringify(history)===before,...result})
}
process.stdout.write(JSON.stringify(rows))
