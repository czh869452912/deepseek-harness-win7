import fs from 'node:fs/promises'
import path from 'node:path'
import {createRequire} from 'node:module'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {LocalCredentialProvider}=await load('packages/credentials/credentials-local/src/index.ts')
const yaml=createRequire(path.join(process.argv[2]!,'packages/credentials/credentials-local/package.json'))('yaml')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),directory=path.join(path.dirname(process.argv[3]!),'files/source'),rows:any[]=[]
await fs.mkdir(directory,{recursive:true})
function normalized(value:any):any{
 if(typeof value==='bigint')return{$integer:String(value)}
 if(value instanceof Date)return{$date:value.toISOString()}
 if(value instanceof Set)return{$set:[...value].map(normalized)}
 if(value instanceof Map)return{$map:[...value].map(([key,value])=>[normalized(key),normalized(value)])}
 if(Buffer.isBuffer(value))return{$bytes:[...value]}
 if(Array.isArray(value))return value.map(normalized)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalized(item)]))
 return value
}
for(const [index,entry]of inputs.entries()){
 const filename=path.join(directory,index+'.yaml'),ctx=new Context();let error=null
 if(entry.text!==null)await fs.writeFile(filename,entry.text,{mode:0o600})
 try{
  await ctx.plugin(LocalCredentialProvider,{path:filename,watch:false})
  if(entry.section==='refs'){
   if('value'in entry)await ctx.credentials.set(entry.key,entry.value)
   else await ctx.credentials.unset(entry.key)
  }else{
   if('value'in entry)await ctx.credentials.modifyRecord(entry.key,async()=>entry.value)
   else await ctx.credentials.deleteRecord(entry.key)
  }
 }catch(failure:any){error=failure.message.replaceAll(filename,'<document>')}
 finally{await ctx.fiber.dispose()}
 let text=null
 try{text=await fs.readFile(filename,'utf8')}catch(failure:any){if(failure.code!=='ENOENT')throw failure}
 let document=null
 if(text!==null)document=normalized(yaml.parseDocument(text,{intAsBigInt:true}).toJS())
 const comments=text===null?[]:[...text.matchAll(/# (c-[a-z-]+)/g)].map(match=>match[1])
 rows.push({error,present:text!==null,document,comments})
}
process.stdout.write(JSON.stringify(rows))
