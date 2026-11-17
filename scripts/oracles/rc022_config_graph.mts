import fs from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
const S=(await load('vendor/schemastery/src/index.ts')).default,{createConfigProjector}=await load('packages/boot/app-boot/src/config-schema/projector.ts')
const entries=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows=[]
function schema(entry:any,calls:string[]):any{
 switch(entry.kind){
  case 'string':return S.string()
  case 'required':return S.string().required()
  case 'default':return S.number().default(3)
  case 'bad-default':return S.number().default('bad')
  case 'object':return S.object({token:S.string().required(),nested:S.object({flag:S.boolean()})})
  case 'shared':{const node=S.string().required();return S.object({a:node,b:node})}
  case 'recursive':{const node=new S({type:'object'});node.dict={child:node};return node}
  case 'transform':return S.transform(S.dict(S.number(),S.string()),()=>{calls.push('transform');throw Error('transform must not execute')})
  case 'volatile':return S.array(S.string().volatile())
  case 'constant':return S.const({constructor:3,a:null,b:[1,2]})
  case 'annotations':return S.string().description({en:'English',zh:'中文'}).role('secret').default('abc')
  case 'pattern':{const node=S.string();node.meta.pattern={source:entry.source,flags:entry.flags};return node}
 }
 const mode=entry.mode,shared=S.string(),node=new S({type:'lazy'})
 node.builder=()=>{
  calls.push('builder')
  if(mode==='cycle')return node
  if(mode==='bad')return 42
  if(mode==='throw')throw Error('builder failed')
  if(mode==='volatile')return S.string().volatile()
  if(mode==='mutation')shared.meta.required=true
  if(mode==='replace-meta')shared.meta={required:true}
  return S.object({value:shared})
 }
 if(mode==='cached')node.inner=S.string()
 if(mode==='loose')node.meta.loose=true
 if(mode==='metadata')node.meta.required=true
 if(mode==='mutation'||mode==='replace-meta')return S.object({before:shared,lazy:node,after:shared})
 if(mode==='shared')return S.object({a:node,b:node})
 return node
}
for(const entry of entries){
 const calls:string[]=[],root=schema(entry,calls),row:any={case:entry,calls},project=await createConfigProjector()
 try{row.value=project(root,'live')}catch(error:any){row.error=error.message}
 rows.push(row)
}
console.log(JSON.stringify(rows))
