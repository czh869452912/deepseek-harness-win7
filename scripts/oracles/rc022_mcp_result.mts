import fs from 'node:fs'
import path from 'node:path'
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const entry=path.join(path.dirname(require.resolve('@modelcontextprotocol/client')),'src-xKF0PJN-.mjs')
const temporary=path.join(path.dirname(entry),'.rc022-result-'+process.pid+'.mjs');let created=false
function normalize(value:any):any{
 if(value instanceof Error)return {name:value.name,message:value.message,...'code'in value?{code:value.code}:{},...'data'in value&&value.data!==undefined?{data:normalize(value.data)}:{}}
 if(Array.isArray(value))return value.map(normalize)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([,v])=>v!==undefined).map(([k,v])=>[k,normalize(v)]))
 return value
}
try{
 fs.writeFileSync(temporary,fs.readFileSync(entry,'utf8')+'\nexport {rev2026Codec as rc022Codec};\n',{flag:'wx'});created=true
 const {rc022Codec}=await import(pathToFileURL(temporary).href)
 process.stdout.write(JSON.stringify(input.map(({method,raw}:any)=>{
  const decoded=rc022Codec.decodeResult(method,raw)
  return normalize({decoded,...decoded.kind==='complete'?{validation:rc022Codec.validateResult(method,decoded.result)}:{}})
 })))
}finally{if(created)fs.unlinkSync(temporary)}
