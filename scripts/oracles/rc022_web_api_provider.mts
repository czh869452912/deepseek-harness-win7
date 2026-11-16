import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {DeepSeekSearchApiProvider:Search,mapSearchResponse}=await load('packages/web/web-deepseek-api/src/search.ts')
const {DeepSeekFetchApiProvider:Fetch}=await load('packages/web/web-deepseek-api/src/fetch.ts')
const inputs=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],originalFetch=globalThis.fetch
const performanceDescriptor=Object.getOwnPropertyDescriptor(globalThis,'performance'),timer=globalThis.setTimeout,clear=globalThis.clearTimeout
try{
 for(const entry of inputs){
  const kind=entry.kind
  let result:any
  if(kind==='snapshot-error'){
   const provider=new (entry.provider==='search'?Search:Fetch)(()=>{throw Error('snapshot-failed')});let returned=false
   try{const operation=provider[entry.provider]({});returned=true;await operation}
   catch(error:any){result={returned,message:error.message}}
  }else if(kind==='map'){
   try{result=mapSearchResponse(entry.payload)}catch(error:any){result={code:error.code,message:error.message}}
  }else if(kind==='rate'){
   const controller=new AbortController(),waits:number[]=[];let now=entry.now
   Object.defineProperty(globalThis,'performance',{configurable:true,value:{now:()=>now}})
   globalThis.setTimeout=((callback:any,ms:number)=>{waits.push(ms);queueMicrotask(()=>{if(entry.abort)controller.abort(Error('fixture-cancel'));else{now+=ms;callback()}});return 1}) as any
   globalThis.clearTimeout=(()=>{}) as any
   const provider=new Search(()=>({}));provider.starts=[...entry.starts]
   try{await provider.waitForRequestSlot(entry.limit,controller.signal);result={admitted:true}}
   catch(error:any){result={code:error.code,message:error.message}}
   result={...result,now,starts:provider.starts,waits}
   Object.defineProperty(globalThis,'performance',performanceDescriptor!)
   globalThis.setTimeout=timer;globalThis.clearTimeout=clear
  }else{
   let reads=0;const sent:any[]=[]
   let options={auth:{sources:[{kind:'api-key',baseURL:entry.base??'https://api.test',key:entry.key??'fixture-key'}]},
    count:'count'in entry?entry.count:10,requestsPerSecond:5,originalQuestion:()=>entry.question??undefined,
    guidance:{subject:'Search',plugin:'web-deepseek-api',custom:true,baseURLField:'searchBaseURL',apiKeyEnvField:'searchApiKeyEnv'}}
   const snapshot=()=>{reads++;return options},search=new Search(snapshot),fetch=new Fetch(snapshot)
   globalThis.fetch=async(endpoint:any,init:any)=>{
    sent.push({path:kind==='fetch'?'/fetch':'/search',body:JSON.parse(init.body)})
    return new Response(JSON.stringify(kind==='fetch'?entry.payload:{results:[]}))
   }
   if(kind==='available')result={search:search.available(),fetch:fetch.available()}
   else{
    try{
     const operation=kind==='fetch'?fetch.fetch({url:'https://page.test/path'}):search.search({query:'fixture',maxResults:entry.bound??undefined})
     options={...options,count:49,originalQuestion:()=>'changed-after-call'}
     result={value:await operation}
    }catch(error:any){result={code:error.code,message:error.message}}
    result={...result,sent,reads}
   }
  }
  rows.push({kind,result})
 }
 rows.push({kind:'description',search:new Search(()=>({})).description,fetch:new Fetch(()=>({})).description})
}finally{
 globalThis.fetch=originalFetch;Object.defineProperty(globalThis,'performance',performanceDescriptor!)
 globalThis.setTimeout=timer;globalThis.clearTimeout=clear
}
process.stdout.write(JSON.stringify(rows))
