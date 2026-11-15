import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const ts=await load('node_modules/typescript/lib/typescript.js'),{deepFreeze}=await load('packages/util/values/src/index.ts')
const source=readFileSync(resolve(process.argv[2]!, 'packages/experimental/auto-review/src/index.ts'),'utf8')
const helpers=source.slice(source.indexOf('function json('),source.indexOf('/** Count members'))
const code=ts.transpileModule(helpers,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText
const {snapshotAutoReview,reviewMessages}=new Function('deepFreeze',code+'\nreturn {snapshotAutoReview,reviewMessages}')(deepFreeze)
const rows:any[]=[]
for(const item of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const session={header:item.meta,surface:{nodes:item.nodes},snapshotEvents:()=>item.events,requestHeader:()=>item.header??undefined,isOwnSeq:(seq:number)=>seq>=item.own}
 let result
 try{const snapshot=snapshotAutoReview({session},item.execution,'C:/current 🐱',new Map(Object.entries(item.shown??{})));result={snapshot,messages:reviewMessages(snapshot)}}catch(error:any){result={error:error.message}}
 rows.push({name:item.name,result})
}
console.log(JSON.stringify(rows))
