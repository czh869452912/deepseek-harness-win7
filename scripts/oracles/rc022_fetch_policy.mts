import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const p=await load('packages/web/web-fetch-http/src/policy.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs){
 let result:any
 try{
  if(entry.kind==='url'){
   const url=p.validateFetchUrl(entry.value);result={}
   for(const key of ['href','origin','protocol','pathname','search','hash'])result[key]=url[key]
  }else if(entry.kind==='content')result={kind:p.classifyContentType(entry.value)??null,charset:p.parseCharset(entry.value)??null}
  else{
   const decoder=p.decoderForCharset(entry.charset??entry.value??undefined)
   result={encoding:decoder.encoding,fatal:decoder.fatal}
   if(entry.kind==='chunks'){
    try{result.chunks=[];for(const byte of entry.data)result.chunks.push(decoder.decode(Uint8Array.of(byte),{stream:true}));result.chunks.push(decoder.decode())}
    catch{result.decodeFailed=true}
   }else if(entry.kind==='decode'){
    try{result.decoded=decoder.decode(Uint8Array.from(entry.data),{stream:entry.stream})}
    catch{result.decodeFailed=true}
   }
  }
 }catch(error:any){result={code:error.code??null,message:error.message}}
 rows.push({kind:entry.kind,result})
}
process.stdout.write(JSON.stringify(rows))
