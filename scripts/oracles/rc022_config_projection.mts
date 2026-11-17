import {load} from './rc022_subagent_fixture.mts'
const S=(await load('vendor/schemastery/src/index.ts')).default
const {createConfigProjector}=await load('packages/boot/app-boot/src/config-schema/projector.ts')
const entries:any[]=[]
const add=(name:string,root:any,builders=new Map(),repeat=false)=>entries.push({name,roots:repeat?[root,root]:[root],builders})
for(const [name,node] of [['any',S.any()],['never',S.never()],['string',S.string()],['number',S.number()],['boolean',S.boolean()],['const-null',S.const(null)],['const-undefined',S.const(undefined)]]) {
 for(const required of [false,true])add(name+'-'+required,required?node.required():node)
}
for(const value of [null,undefined,0,3,-2.5,'bad',false,[],{},NaN,Infinity])add('default-'+String(value),S.number().default(value))
for(const [minimum,maximum,step] of [[0,10,1],[1,10,2],[0,10,2],[0,10,.1],[-Infinity,Infinity,0],[-Infinity,3,2],[NaN,4,0],[1,NaN,0],[3,2,0]]) {
 const node=S.number();node.meta={min:minimum,max:maximum,step};add('number-'+entries.length,node)
}
for(const [minimum,maximum] of [[0,0],[1,1],[2,4],[.5,2.5],[-1,-1],[Infinity,Infinity]]) {
 const node=S.string();node.meta={min:minimum,max:maximum};add('string-range-'+entries.length,node)
}
for(const source of ['','^abc$','a|b','[a-z]+','[^x]','[\\d\\s]','^.*foo$','.*a.*','\\b.*x','.', '\\D','(.)','(?:ab)','a{2,3}','\\u{1F600}','😀','[\\uD800-\\uDFFF]','(?=a)b','(?<word>a)','\\w+','^a+$','[a-z]','a\\b','a\\1']) {
 for(const flags of ['', 'u','i','m']) {
  try{const regex=new RegExp(source,flags);add('pattern-'+source+'-'+flags,S.string().pattern(regex))}catch{}
 }
}
add('object',S.object({token:S.string().required(),nested:S.object({flag:S.boolean()})}))
add('arrays',S.array(S.number().required()).min(1).max(3))
add('array-default-item',S.array(S.number().default(1)).min(3))
add('tuple',S.tuple([S.string().required(),S.number()]))
add('tuple-empty',S.tuple([]))
add('dict',S.dict(S.number(),S.string().pattern(/^[a-z]+$/)))
add('dict-total',S.dict(S.number(),S.string()))
add('union',S.union([S.string().required(),S.number()]))
add('union-writeback',S.union([S.object({value:S.transform(S.number(),()=>{throw Error('transform must not execute')})}),S.string()]))
add('transform',S.transform(S.dict(S.number(),S.string().pattern(/^a/)),()=>{throw Error('transform must not execute')}))
add('loose',S.number().loose().default('bad'))
add('volatile-fixed',S.object({field:S.string().volatile()}))
add('volatile-array',S.array(S.string().volatile()))
add('volatile-nested',S.object({field:S.string().volatile()}).volatile())
for(const value of [{a:null,b:undefined,c:3},[null,undefined,3],{constructor:3,toString:null}, {['__proto__']:3},new Date(0),/x/u,NaN,BigInt(1)]) add('constant-'+entries.length,S.const(value))
const annotated=S.string().description({en:'English',zh:'中文'}).role('secret').default('abc')
Object.assign(annotated.meta,{extra:{unit:'ms'},hidden:true,disabled:false,collapse:true,link:'https://example.invalid',comment:'note',badges:[{text:'one'}]});add('annotations',annotated)
for(const [name,value] of [['cycle',null],['date',new Date(0)],['regexp',/x/],['callback',()=>{}],['bigint',BigInt(1)],['nan',NaN]]) {
 const node=S.string();const cycle:any={};cycle.self=cycle;node.meta.default=name==='cycle'?cycle:value;add('annotation-'+name,node)
}
for(const mode of ['cached','fresh','loose','metadata','cycle','bad','throw']) {
 const node=new S({type:'lazy'}),inner=S.object({value:S.string()});const builders=new Map()
 if(mode==='cached')node.inner=inner
 else if(mode==='cycle'){node.builder=()=>node;builders.set(node,{value:node})}
 else if(mode==='bad'){node.builder=()=>42;builders.set(node,{value:42})}
 else if(mode==='throw'){node.builder=()=>{throw Error('builder failed')};builders.set(node,{error:'builder failed'})}
 else {node.builder=()=>inner;builders.set(node,{value:inner})}
 if(mode==='loose')node.meta.loose=true
 if(mode==='metadata')node.meta.required=true
 add('lazy-'+mode,node,builders,true)
}
const recursive=new S({type:'object'});recursive.dict={child:recursive};add('recursive-object',recursive,new Map(),true)
const shared=S.number().required();add('shared',S.object({a:shared,b:shared}))
for(const type of ['custom','intersect','bitset'])add('unsupported-'+type,new S({type}))
for(const type of ['array','tuple','transform','dict'])add('missing-'+type,new S({type}))

const output=[]
for(const entry of entries){
 const heap:any[]=[],seen=new Map<any,number>(),builderCalls:number[]=[]
 const encode=(value:any):any=>{
  if(value===undefined)return {atom:'undefined'}
  if(typeof value==='number'&&!Number.isFinite(value))return {atom:Number.isNaN(value)?'nan':value<0?'-infinity':'infinity'}
  if(typeof value==='bigint')return {atom:'bigint',value:String(value)}
  if(typeof value==='symbol')return {atom:'symbol',value:value.description}
  if(value===null||!['object','function'].includes(typeof value))return value
  if(seen.has(value))return {ref:seen.get(value)}
  const index=heap.length;seen.set(value,index);const record:any={};heap.push(record)
  if(value[Symbol.for('schemastery')]===true){
   record.kind='schema';record.entries=[]
   for(const key of ['type','meta','value','inner','sKey','list','dict'])if(key in value)record.entries.push([key,encode(value[key])])
   const builder=entry.builders.get(value)
   if(builder){record.builder=Object.hasOwn(builder,'error')?{error:builder.error}:encode(builder.value);const original=value.builder;value.builder=function(){builderCalls.push(index);return Reflect.apply(original,this,[])}}
  }else if(Array.isArray(value)){record.kind='array';record.items=Array.from(value,encode)}
  else if(value instanceof Date){record.kind='date';record.value=value.toISOString()}
  else if(value instanceof RegExp){record.kind='regexp';record.source=value.source;record.flags=value.flags}
  else if(typeof value==='function')record.kind='function'
  else {record.kind='object';record.entries=Object.entries(value).map(([key,item])=>[key,encode(item)])}
  return {ref:index}
 }
 const roots=entry.roots.map(encode),wire={heap,roots},project=await createConfigProjector()
 const results=entry.roots.map((root:any,index:number)=>{try{return {value:project(root,'graph'+index)}}catch(error:any){return {error:error.message}}})
 output.push({name:entry.name,wire,observation:{results,builderCalls}})
}
console.log(JSON.stringify(output))
