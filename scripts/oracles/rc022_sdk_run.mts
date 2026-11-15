import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {createProcessDeepSeekHarness}=await load('packages/sdk/client/src/api.ts')
const cases=JSON.parse(readFileSync(new URL('../../tests/fixtures/rc022_sdk_run.json',import.meta.url),'utf8')),rows:any[]=[]
for(const entry of cases){
 const env={...process.env};for(const key of Object.keys(env))if(key.startsWith('QUERY_'))delete env[key]
 for(const [key,target] of [['result','QUERY_RESULT'],['completion','QUERY_COMPLETION']])if(Object.hasOwn(entry,key))env[target]=JSON.stringify(entry[key])
 if(entry.lifecycle!==undefined)env.QUERY_LIFECYCLE=entry.lifecycle
 const harness=createProcessDeepSeekHarness({command:process.execPath,args:[resolve(process.argv[2]!,'packages/sdk/client/tests/fixtures/query.ts')],environment:()=>env,description:'query protocol fixture',initializeTimeoutMs:5000,requestTimeoutMs:5000,shutdownTimeoutMs:5000}),seen:any[]=[]
 const observer=(note:any)=>{if(entry.observerError)throw Error('observer failed');seen.push(note)}
 try{
  let result:any;try{result={value:await harness.run(entry.input??'input',{sessionId:'main',onNotification:observer})}}catch(error){result={error:(error as Error).message}}
  const state=await harness.client.request('test/state') as any
  // Completion has closed the run's subscription; no extra global subscription is installed.
  rows.push({name:entry.name,result,seen,queries:state.queries,subscriptions:0})
 }finally{await harness.close()}
}
console.log(JSON.stringify(rows))
