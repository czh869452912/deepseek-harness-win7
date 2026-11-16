import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {parsePublicUrl}=await load('packages/bundle/web-app/src/public-url.ts')
const corpus=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
process.stdout.write(JSON.stringify(corpus.map((value:string)=>{
 try{return {value,url:parsePublicUrl(value).href}}catch(error){return {value,error:(error as Error).message}}
})))
