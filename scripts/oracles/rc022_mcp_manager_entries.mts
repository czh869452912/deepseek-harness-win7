import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const original=path.join(root,'packages/mcp/mcp-manager/src/index.ts'),temporary=path.join(path.dirname(original),'.rc022-manager-entries-'+process.pid+'.ts')
let created=false
try{
 fs.writeFileSync(temporary,fs.readFileSync(original,'utf8')+'\nexport { ServerEntrySchema, validateEntries };\n',{flag:'wx'});created=true
 const {default:Manager,ServerEntrySchema,validateEntries}=await import(pathToFileURL(temporary).href)
 const rows=input.map((item:any)=>{
  let result
  try{
   const entry=ServerEntrySchema(item.entry);validateEntries({[item.name]:entry})
   const client=Manager.prototype.toClientConfig.call({},item.name,entry)
   for(const key of ['args','env','headers'])if(key in client&&client[key]===entry[key])throw new Error('conversion retained raw collection')
   result={entry,client}
  }catch(error){result={error:{name:error.name,message:error.message}}}
  return {input:item,result}
 })
 process.stdout.write(JSON.stringify(rows))
}finally{if(created)fs.unlinkSync(temporary)}
