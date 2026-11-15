import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),Backend=await load('packages/session/session-persistence-jsonl/src/index.ts')
const results:any[]=[]
for(const limit of [1,2,3])for(const names of [[],['p0'],['p1'],['p2'],['d00'],['d01'],['d10'],['p1','d01'],['p2','d10']]){
 const ctx=new Context();await ctx.plugin(Backend,{root:'unused',listConcurrency:limit});const backend:any=ctx.sessionPersistence
 let active=0,peak=0;const completed:string[]=[],failures=new Map(names.map(name=>[name,new Error(name)]))
 async function read(name:string,value:any){active++;peak=Math.max(peak,active);try{await new Promise(resolve=>setTimeout(resolve,['p0','d00'].includes(name)?8:1));if(failures.has(name))throw failures.get(name);return value}finally{active--;completed.push(name)}}
 backend.listProjectDirs=()=>read('root',['p0','p1','p2'])
 backend.listSessionDirs=(project:string)=>read(project,[0,1].map(i=>'d'+project[1]+i))
 const task=(directory:string)=>read(directory,directory)
 async function listing(){try{return {values:await backend.mapSessionDirectories(task)}}catch(error:any){return {error:error.message,same:failures.get(error.message)===error}}}
 const values=await Promise.all([listing(),listing()]);results.push({limit,failures:names,peak,active,completed:completed.sort(),values});await ctx.fiber.dispose()
}
const configs=[]
for(const value of [null,1,2,0,-1,1.5,true,'2']){try{configs.push({value,limit:Backend.Config({root:'unused',...value===null?{}:{listConcurrency:value}}).listConcurrency})}catch{configs.push({value,rejected:true})}}
results.push({configs});process.stdout.write(JSON.stringify(results))
