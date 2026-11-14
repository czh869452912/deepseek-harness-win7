import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const {default:Hmr}=await import(pathToFileURL(resolve(process.argv[2]!,'packages/boot/hmr/src/index.ts')).href)
const result=[]
for(const row of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const owner:any={stashed:new Set(row.stashed),externals:new Set(row.externals),getLinked:async(url:string)=>row.graph[url]??[]}
 await (Hmr.prototype as any).analyzeChanges.call(owner)
 result.push({accepted:[...owner.accepted],declined:[...owner.declined]})
}
process.stdout.write(JSON.stringify(result))
