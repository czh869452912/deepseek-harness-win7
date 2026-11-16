import fs from 'node:fs'
import path from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {parseCredentialsDocument}=await load('packages/credentials/credentials-local/src/index.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],raw:any[]=[]
for(const [index,text]of inputs.entries()){
 try{
  const result=parseCredentialsDocument(text,'<document>')
  rows.push({value:{refs:Object.fromEntries(result.refs),records:Object.fromEntries(result.records),ignoredKeys:result.ignoredKeys}})
 }catch(error:any){
  let message=error.message
  if(message.startsWith('credentials-local: invalid document at <document>: ')){
   raw.push({index,error:message});message='credentials-local: invalid document at <document>: <runtime YAML diagnostic>'
  }
  rows.push({error:message})
 }
}
fs.writeFileSync(path.join(path.dirname(process.argv[3]!),'source-parser-diagnostics.json'),JSON.stringify(raw))
process.stdout.write(JSON.stringify(rows))
