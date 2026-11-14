/** Run the supplied corpus against unchanged fixed Source APIs. */
import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const base=process.argv[2]!,load=async(path:string)=>import(pathToFileURL(resolve(base,path)).href)
const {default:z}=await load('vendor/schemastery/src/index.ts')
const {createVolatile,isVolatile,volatileEntries}=await load('vendor/cosmokit/src/volatile.ts')
const {deepEqual}=await load('vendor/cosmokit/src/types.ts')
const {equalExceptVolatile}=await load('vendor/loader/src/config/diff.ts')
function decode(value:any):any{
 if(value&&typeof value==='object'&&!Array.isArray(value)&&'$type' in value){
   if(value.$type==='undefined')return undefined
   if(value.$type==='ref')return createVolatile(decode(value.value))
   if(value.$type==='cycle'){const result:any={};result.self=result;return result}
   if(value.$type==='opaque')return new(class{value=1})()
   if(value.$type==='date')return new Date(value.value)
   if(value.$type==='function')return ()=>1
 }
 if(Array.isArray(value))return value.map(decode)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,decode(item)]))
 return value
}
function normalize(value:any):any{
 if(value===undefined)return {$type:'undefined'}
 if(isVolatile(value))return {$type:'ref',value:normalize(value.get())}
 if(Array.isArray(value))return value.map(normalize)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)]))
 return value
}
function schema(name:string):any{
 const live=()=>z.string().volatile()
 if(name==='config')return z.object({fixed:z.string().default('fixed'),title:z.string().default('hello').volatile(),optional:live(),nested:z.object({count:z.number().min(0).volatile().default(1)}).default({}),group:z.object({list:z.array(z.string())}).default({list:[]}).volatile()})
 if(name==='scalar')return live().default('hello')
 if(name==='array')return z.array(z.string()).volatile()
 if(name==='union')return z.union([z.string(),z.number()]).volatile()
 if(name==='date')return z.object({block:z.object({when:z.date().volatile()})})
 if(name==='bad-array')return z.object({items:z.array(live())})
 if(name==='bad-dict')return z.object({items:z.dict(live())})
 if(name==='bad-union')return z.union([z.object({title:live()}),z.string()])
 if(name==='bad-tuple')return z.object({items:z.tuple([live()])})
 if(name==='bad-intersect')return z.intersect([z.object({title:live()})])
 if(name==='bad-transform')return z.transform(z.object({title:live()}),(value:any)=>value)
 if(name==='bad-nested')return z.object({block:z.object({title:live()}).volatile()})
 if(name==='bad-lazy')return z.object({lazy:z.lazy(()=>z.object({live:live()}))})
 if(name==='metadata-free')return new z({type:'object',dict:{enabled:{type:'boolean'}}})
 if(name==='raw-nested')return z.object({nested:z.object({live:live(),fixed:z.string()}).default({fixed:'default'})})
 if(name==='raw-shared'){const shared=z.object({value:live()});return z.object({first:shared,second:shared})}
 if(name==='raw-recursive'){const recursive=z.object({value:z.string()}).extra('default',undefined);recursive.set('child',recursive);return recursive}
 return undefined
}
const cases=JSON.parse(readFileSync(process.argv[3]!,'utf8'))
const results=cases.map((row:any)=>{
 try{
  let value:any
  if(row.op==='deep')value=deepEqual(decode(row.left),decode(row.right),row.strict)
  else if(row.op==='diff')value=equalExceptVolatile(decode(row.left),decode(row.right),schema(row.schema))
  else if(row.op==='snapshot'){const reference=createVolatile(decode(row.data));value=[reference.get(),volatileEntries(reference).map((entry:any)=>entry.path)]}
  else{const target=schema(row.schema),parsed=target(decode(row.data),row.options);value={parsed,simplified:target.simplify(parsed),paths:volatileEntries(parsed).map((entry:any)=>entry.path)}}
  return {ok:true,value:normalize(value)}
 }catch(error:any){return {ok:false,name:error.name,message:error.message,path:error.options?.path??[]}}
})
process.stdout.write(JSON.stringify(results))
