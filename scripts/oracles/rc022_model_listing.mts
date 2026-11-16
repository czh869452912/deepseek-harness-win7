import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {parseModelListing,modelListingURL}=await load('packages/llm/llm-deepseek/src/listing.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [kind,values,callback] of [['body',input.bodies,parseModelListing],['url',input.urls,modelListingURL]] as const){
 for(const [index,value] of values.entries()){
  try{rows.push({kind,index,value:callback(value)})}
  catch(error:any){rows.push({kind,index,error:error.message,code:error.code??null})}
 }
}
console.log(JSON.stringify(rows))
