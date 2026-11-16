import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {resolveAdapterOptions}=await load('packages/llm/llm-deepseek/src/config.ts')
const {serialize}=await load('packages/llm/llm-deepseek/src/serialize.ts')
const {translate}=await load('packages/llm/llm-deepseek/src/translate.ts')
const {modelInfo}=await load('packages/llm/llm-deepseek/src/model-info.ts')
const {messagesApiRoot}=await load('packages/llm/llm-deepseek/src/messages-api.ts')
const {BlockAssembler}=await load('packages/llm/llm/src/index.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [index,entry] of input.serial.entries()){
 const degraded:any[]=[],history=structuredClone(entry.history),before=JSON.stringify(history)
 const images=new Map(Object.entries(entry.images??{}).map(([key,value]:[string,any])=>[key,{...value,data:Buffer.from(value.base64,'base64')}]))
 let result:any
 try{result={value:serialize({provider:'deepseek-official',model:'m',system:'base',...entry.options},resolveAdapterOptions(entry.config),history,images,()=>entry.access??undefined,(reason:string)=>degraded.push(reason),entry.fileIds==null?undefined:new Map(Object.entries(entry.fileIds)))}}
 catch(error:any){result={error:error.message,code:error.code??null}}
 rows.push({kind:'serialize',index,degraded,unchanged:JSON.stringify(history)===before,...result})
}
for(const [index,sequence] of input.streams.entries()){
 async function* events(){yield* structuredClone(sequence)}
 const chunks:any[]=[];let result:any={}
 try{for await(const chunk of translate(events(),'m'))chunks.push(chunk)}catch(error:any){result={error:error.message,code:error.code??null}}
 const assembler=new BlockAssembler()
 for(const chunk of chunks)assembler.push(chunk)
 rows.push({kind:'translate',index,chunks,assembled:{blocks:assembler.blocks(),replayState:assembler.replayState??null},...result})
}
for(const [index,entry] of input.info.entries())rows.push({kind:'info',index,value:modelInfo(resolveAdapterOptions(entry.config),'deepseek-official',entry.model)})
for(const [index,url] of input.urls.entries())rows.push({kind:'root',index,value:messagesApiRoot(url)})
console.log(JSON.stringify(rows))
