import {createHash} from 'node:crypto'
import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const api=await load('packages/extensions/tool-cordis/src/api-catalog.ts')
const {hostInspectProviders}=await load('packages/extensions/tool-cordis/src/providers.ts')
if(process.argv[3]==='--export'){
 const path='packages/extensions/tool-cordis/src/api-catalog.ts'
 console.log(JSON.stringify({target_upstream:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',source:path,
  source_sha256:createHash('sha256').update(readFileSync(join(process.argv[2]!,path))).digest('hex'),
  catalogs:Object.fromEntries(['SERVICE_API','EVENT_API','TYPE_API','INHERITED_CTX_API'].map(key=>[key,api[key]])),
  manifests:hostInspectProviders({} as any).map((row:any)=>row.manifest)}))
}else{
 const normalize=(value:any):any=>Array.isArray(value)?value.map(normalize):value!==null&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,normalize(value[key])])):value
 const digest=(value:any)=>{const bytes=Buffer.from(JSON.stringify(normalize(value)));return {sha256:createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length}}
 const rows:any[]=[]
 for(const key of [undefined,...api.SERVICE_API.map((row:any)=>row.key),'','unknown','"中文\n']){
  try{rows.push({kind:'service',key:key??null,...digest(api.queryServiceApi(key))})}catch(error:any){rows.push({kind:'service',key:key??null,error:error.message})}
 }
 const events=api.EVENT_API.filter((row:any)=>!row.name.startsWith('cordis/'))
 for(const key of [undefined,...events.map((row:any)=>row.name),'','unknown','cordis/query','"中文\n']){
  try{rows.push({kind:'event',key:key??null,...digest(api.queryEventApi(key,events))})}catch(error:any){rows.push({kind:'event',key:key??null,error:error.message})}
 }
 rows.push({kind:'manifests',value:hostInspectProviders({} as any).map((row:any)=>row.manifest)})
 console.log(JSON.stringify(rows))
}
