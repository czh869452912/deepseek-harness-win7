import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const d=await load('packages/util/plugin-detail/src/index.ts'),input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const mode of input.cases){
 const signal=new AbortController(),lifetime=new AbortController(),endpoint=['cancel','dispose'].includes(mode)?'headers':mode
 const timer=['cancel','dispose','body'].includes(mode)?setTimeout(()=>(mode==='dispose'?lifetime:signal).abort(new Error('closed')),70):undefined
 let result:any
 try{const value=await d.fetchBody(input.url+'/'+endpoint,mode==='gzip'?40:10,signal.signal,{timeoutMs:mode==='headers'?60:2000,lifetime:lifetime.signal});if(value.ok)value.bytes=new TextDecoder().decode(value.bytes);result={value}}
 catch(error:any){result={error:error.reason??error.message}}
 finally{clearTimeout(timer)}
 rows.push({name:mode,result})
}
const original=globalThis.fetch
try{
 for(const mode of ['fallback','missing','too-large','all-down','cancelled','readme']){
  const requests:string[]=[]
  globalThis.fetch=async(url:any)=>{requests.push(String(url));if(mode==='cancelled')throw new Error('closed');if(mode==='too-large')return new Response('x',{headers:{'content-length':'999'}});if(mode==='missing')return new Response('',{status:404});if(mode==='all-down')throw new Error('offline');if(requests.length===1)return new Response('',{status:503});if(mode==='readme'&&!String(url).endsWith('/readme.md'))return new Response('',{status:404});return new Response('document')}
  const signal=new AbortController();if(mode==='cancelled')signal.abort(new Error('closed'))
  const files=d.npmFiles('@scope/x','1.0.0',['jsdelivr','unpkg','npmmirror'],{timeoutMs:2000,lifetime:new AbortController().signal});let result:any
  try{let value=mode==='readme'?await files.readme('docs',100,signal.signal):await files.read('docs/a b.md',100,signal.signal);if(value instanceof Uint8Array)value=new TextDecoder().decode(value);if(value&&typeof value==='object'&&'bytes'in value)value={path:value.path,bytes:new TextDecoder().decode(value.bytes)};result={value:value??null}}
  catch(error:any){result={error:error.reason??error.message}}
  rows.push({name:'npm-'+mode,result,requests})
 }
}finally{globalThis.fetch=original}
console.log(JSON.stringify(rows))
