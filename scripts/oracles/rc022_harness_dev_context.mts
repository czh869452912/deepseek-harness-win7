import fs from 'node:fs'
import path from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const module=await load('packages/context/harness-dev-context/src/index.ts'),corpus=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
let state:any={source:null,web:null},definition:any,url='http://new:8123/'
const sections:any[]=[],contexts:any[]=[],rows:any[]=[]
const ctx={webApp:{getAdvertisedUrl:()=>url},sessionProjections:{async register(value:any){definition=value;return {stateOf:()=>state}}},
 systemPrompt:{section:(value:any)=>sections.push(value),context:(value:any)=>contexts.push(value),getSectionOrder:(key:string)=>key,getContextOrder:(key:string)=>key}}
await module.apply(ctx as any)
const root=path.resolve(process.argv[2]!)+path.sep
function observe(name:string){rows.push({name,state,sections:sections.map(row=>({...row,text:row.text({agent:{session:{}}})})),contexts:contexts.map(row=>({...row,text:(typeof row.text==='function'?row.text():row.text).replace(JSON.stringify(root),'"<implementation-root>"')}))})}
observe('initial')
for(const item of corpus){state=definition.apply(state,item.event);observe(item.name)}
url='http://changed:9123/';observe('url-changed')
process.stdout.write(JSON.stringify(rows))
