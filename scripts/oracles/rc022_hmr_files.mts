import {mkdirSync,readFileSync,writeFileSync,utimesSync,unlinkSync,linkSync} from 'node:fs'
import {dirname,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {ModuleFiles}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/module-files.ts')).href)
const directory=resolve(dirname(input),'files/source');mkdirSync(directory,{recursive:true})
const tracker=new ModuleFiles(),result:any[]=[]
let seen=new Map<string,string|undefined>()
const url=(name:string)=>name.startsWith('node:')?name:pathToFileURL(resolve(directory,name)).href
for(const [index,step] of JSON.parse(readFileSync(input,'utf8')).entries()){
 const names=(step.names??[]).map(url),file=step.name===undefined?'':resolve(directory,step.name)
 if(['write','replace'].includes(step.op)){
  if(step.op==='replace')unlinkSync(file)
  writeFileSync(file,step.text);utimesSync(file,step.at/1000,step.at/1000)
 }else if(step.op==='unlink')unlinkSync(file)
 else if(step.op==='link')linkSync(file,resolve(directory,step.to))
 else if(step.op==='observe')tracker.observe(names,{at:step.at,retained:new Set((step.retained??[]).map(url)),...step.seen?{seen}:{}})
 else if(step.op==='refresh')tracker.refresh(names)
 else if(step.op==='compare'){
  const value=tracker.compare(names);seen=value.seen
  result.push({step:index,stale:step.names.filter((name:string)=>value.stale.has(url(name))),present:Object.fromEntries(step.names.map((name:string)=>[name,seen.get(url(name))!==undefined]))})
 }
}
process.stdout.write(JSON.stringify(result))
