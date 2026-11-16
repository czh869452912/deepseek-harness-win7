import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {parseSse}=await load('packages/llm/llm-deepseek/src/sse.ts')
const {providerError,providerErrorDetail}=await load('packages/llm/llm-deepseek/src/transport.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [index,chunks] of input.frames.entries()){
 let cursor=0,pulses=0,result:any={};const values:any[]=[]
 const body=new ReadableStream<Uint8Array>({pull(controller){if(cursor<chunks.length)controller.enqueue(Buffer.from(chunks[cursor++],'base64'));else controller.close()}})
 try{for await(const event of parseSse(body,()=>pulses++))values.push(event)}catch(error:any){result={error:error.message,code:error.code??null}}
 rows.push({kind:'sse',index,values,...Object.keys(result).length===0?{pulses}:{},...result})
}
const previous=Date.now
try{
 Date.now=()=>1750000000000
 for(const [index,entry] of input.errors.entries()){
  let result:any
  try{result={failure:providerError(entry.raw,entry.status??undefined,new Headers(entry.headers)).failure,detail:providerErrorDetail(entry.raw)}}
  catch(error:any){result={error:error.message,code:error.code??null}}
  rows.push({kind:'error',index,...result})
 }
}finally{Date.now=previous}
console.log(JSON.stringify(rows))
