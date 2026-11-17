import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
const root=path.resolve(process.argv[2]!),cases=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const {Client}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')).href)
const output=[],realNow=Date.now,realTimeout=globalThis.setTimeout
try{
 for(const fixture of cases){
  let clock=fixture.firstMs,count=1;Date.now=()=>clock
  globalThis.setTimeout=((callback:any,ms:any,...args:any[])=>{if(ms===250){clock+=fixture.paceMs;return realTimeout(callback,0,...args)}return realTimeout(callback,ms,...args)}) as any
  const client=new Client({name:'probe',version:'1'},{inputRequired:{maxRounds:fixture.maxRounds??10}}),retries:any[]=[],progress:any[]=[]
  const options:any={...fixture.options,onprogress:(value:any)=>progress.push(value)};if('budget' in fixture)options.maxTotalTimeout=fixture.budget
  let result
  try{result={value:await client._resolveNonCompleteResult({kind:'input_required',inputRequests:{},requestState:'state1'},{request:{method:'tools/list'},options,flowStartedAt:0,
   retry:async(params:any,options:any)=>{const {onprogress,...serial}=options;retries.push({state:params.requestState,options:serial,keys:Object.keys(options).sort()});clock+=fixture.legMs;count++;return count<=fixture.rounds?{resultType:'input_required',inputRequests:{},requestState:'state'+count}:{tools:[],ttlMs:0,cacheScope:'private'}}})}}
  catch(error:any){result={error:{name:error.name,message:error.message,code:error.code,data:error.data}}}
  output.push({name:fixture.name,result,retries,progress,elapsed:clock})
 }
}finally{Date.now=realNow;globalThis.setTimeout=realTimeout}
process.stdout.write(JSON.stringify(output))
