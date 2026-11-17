import fs from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
const {queryEnvironment}=await load('packages/client/product-analytics/src/environment-query.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs.cases){
 const controller=new AbortController()
 if(entry.preabort)controller.abort()
 const timer=entry.abortMillis===undefined?undefined:setTimeout(()=>controller.abort(),entry.abortMillis)
 try{rows.push(await queryEnvironment(entry.missing?inputs.node+'-missing':inputs.node,['-e',entry.code??''],{
  signal:controller.signal,timeoutMillis:entry.timeoutMillis??3000,maxOutputBytes:entry.maxOutputBytes??16384}))}
 finally{clearTimeout(timer)}
}
console.log(JSON.stringify(rows))
