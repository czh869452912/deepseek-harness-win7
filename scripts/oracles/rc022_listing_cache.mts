import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {ModelListingCache}=await load('packages/llm/llm-deepseek/src/listing-cache.ts')
const ops=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const state:any={token:'a',now:0,credentialError:false,settings:true},settings={url:'https://api.example/models',timeoutMs:10000,maxAgeMs:1000000}
const loads:any[]=[],info:any[]=[],warn:any[]=[],changed:any[]=[],views:any={},controllers:any={},outcomes:any={},snapshots:any[]=[]
function listing(id:string,badge?:string){return{entries:[{id,requirement:{kind:'none'},capabilities:{usable:true,facts:{inputModalities:['text']}},...badge===undefined?{}:{badge:{kind:'badge',badge:{text:badge,tone:'info'}}}}],skipped:0}}
const cache=new ModelListingCache({settings:()=>state.settings?settings:undefined,credential:async()=>{if(state.credentialError)throw new Error('credential lookup');return state.token??undefined},load:(url:string,token:string,signal:AbortSignal)=>{const future=Promise.withResolvers();loads.push({url,token,signal,future});return future.promise},now:()=>state.now,info:(message:string)=>info.push(message),warn:(message:string)=>warn.push(message),changed:()=>changed.push(true)})
function current(){const result=cache.current();return{authenticated:result.authenticated,listing:result.listing??null}}
const flush=()=>new Promise(resolve=>setImmediate(resolve))
let disposing:Promise<void>|undefined,disposalDone=false
try{
 for(const op of ops){
  const kind=op[0]
  if(kind==='token')state.token=op[1]
  else if(kind==='advance')state.now+=1000000
  else if(kind==='credential-error')state.credentialError=op[1]
  else if(kind==='settings-off')state.settings=false
  else if(kind==='settings-on')state.settings=true
  else if(kind==='view'){const controller=controllers[op[1]]=new AbortController();views[op[1]]=cache.view(settings,op.length>2?controller.signal:undefined);views[op[1]].catch(()=>{})}
  else if(kind==='await'){try{const result=await views[op[1]];outcomes[op[1]]={authenticated:result.authenticated,listing:result.listing??null}}catch(error:any){outcomes[op[1]]={error:error.message}}}
  else if(kind==='abort')controllers[op[1]].abort(new Error('caller left'))
  else if(kind==='resolve')loads[op[1]].future.resolve(listing(op[2],op[3]))
  else if(kind==='reject')loads[op[1]].future.reject(new Error('offline'))
  else if(kind==='invalidate')cache.invalidate()
  else if(kind==='refresh')await cache.refresh(settings)
  else if(kind==='dispose-start'){disposing=cache.dispose().then(()=>{disposalDone=true})}
  else if(kind==='dispose-await')await disposing
  else if(kind==='snapshot')snapshots.push({name:op[1],current:current(),loads:loads.map(({url,token,signal})=>({url,token,aborted:signal.aborted})),info:[...info],warn:[...warn],changed:changed.length,outcomes:{...outcomes},disposalDone})
  await flush()
 }
 process.stdout.write(JSON.stringify(snapshots))
}finally{for(const row of loads)row.future.resolve(listing('cleanup'));await cache.dispose();await Promise.allSettled(Object.values(views))}
