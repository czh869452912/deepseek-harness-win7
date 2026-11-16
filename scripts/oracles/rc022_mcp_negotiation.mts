import fs from 'node:fs'
import path from 'node:path'
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const entry=require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')
const temporary=path.join(path.dirname(entry),'.rc022-negotiation-'+process.pid+'.mjs')
let created=false
function normalize(value:any):any{
 if(value instanceof Error)return {name:value.name,message:value.message,...'code'in value?{code:value.code}:{},...'data'in value&&value.data!==undefined?{data:normalize(value.data)}:{}}
 if(Array.isArray(value))return value.map(normalize)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([,v])=>v!==undefined).map(([k,v])=>[k,normalize(v)]))
 return value
}
try{
 fs.writeFileSync(temporary,fs.readFileSync(entry,'utf8')+'\nexport {classifyProbeOutcome as rc022Classify};\n',{flag:'wx'});created=true
 const {rc022Classify}=await import(pathToFileURL(temporary).href)
 const rows=input.map(({outcome,context}:any)=>{
  if(outcome.error&&typeof outcome.error==='object'&&outcome.error.fixtureError){const spec=outcome.error;outcome.error=spec.name==='TypeError'?new TypeError(spec.message):new Error(spec.message);if(spec.name)outcome.error.name=spec.name}
  return normalize(rc022Classify(outcome,context))
 })
 process.stdout.write(JSON.stringify(rows))
}finally{if(created)fs.unlinkSync(temporary)}
