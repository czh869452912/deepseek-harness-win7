import {mkdirSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source')
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/src/index.ts')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
mkdirSync(directory,{recursive:true});const result:any[]=[]
for(const mode of ['static-dynamic','runtime-import']){
 const packageDir=join(directory,mode);mkdirSync(packageDir)
 const suffix=mode==='static-dynamic'?'.mjs':'.cjs',paths=['entry','dep','late'].map(name=>join(packageDir,name+suffix))
 writeFileSync(paths[1]!,mode==='static-dynamic'?'export const value=1\n':'exports.value=1\n');writeFileSync(paths[2]!,mode==='static-dynamic'?'export const value=2\n':'exports.value=2\n')
 writeFileSync(paths[0]!,mode==='static-dynamic'?`import {value} from './dep.mjs';export const first=value;export async function later(){return (await import('./late.mjs')).value}\n`:`const {value}=require('./dep.cjs');exports.first=value;exports.later=()=>require('./late.cjs').value\n`)
 const urls=paths.map(path=>pathToFileURL(path).href),labels=new Map(urls.map((url,index)=>[url,['entry','dep','late'][index]]))
 const ctx=new Context();await ctx.plugin(Loader)
 try{
  const entry:any=await ctx.loader.import(urls[0]!,()=>[]),target=Object.assign(Object.create(Hmr.prototype),{internal:ctx.loader.internal})
  const edges=async()=>{
   const graph=await target.moduleGraph(),values:any[]=[]
   for(const [child,parents] of graph)for(const parent of parents)if(labels.has(child)&&labels.has(parent))values.push([labels.get(parent),labels.get(child)])
   return values.sort((left,right)=>JSON.stringify(left).localeCompare(JSON.stringify(right)))
  }
  const before=await edges(),value=await entry.later(),after=await edges();writeFileSync(paths[0]!,'throw new Error("new disk code")\n')
  result.push({mode,before,after,after_disk:await edges(),value})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
