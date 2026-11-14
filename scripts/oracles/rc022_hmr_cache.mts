import {mkdirSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source')
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/src/index.ts')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
mkdirSync(directory,{recursive:true})
const result:any[]=[]
for(const mode of ['success','failure','unrelated']){
 const file=join(directory,mode+'.mjs'),url=pathToFileURL(file).href;writeFileSync(file,'export const value = 1\n')
 const ctx=new Context();await ctx.plugin(Loader)
 try{
  const first:any=await ctx.loader.import(url,()=>[]);writeFileSync(file,mode==='failure'?'export const value = (\n':'export const value = 2\n')
  const retained:any=await ctx.loader.import(url,()=>[])
  const target=Object.assign(Object.create(Hmr.prototype),{internal:ctx.loader.internal})
  const rollback=target.evict(mode==='unrelated'?['node:fs',pathToFileURL(join(directory,'absent.mjs')).href]:[url])
  let failed=false,value:any=null,replaced:any=null
  try{const fresh:any=await ctx.loader.import(url,()=>[]);value=fresh.value;replaced=fresh!==first}catch{failed=true}
  rollback();const restored:any=await ctx.loader.import(url,()=>[])
  result.push({case:mode,retained:retained===first,retained_value:retained.value,failed,value,replaced,restored:restored===first,restored_value:restored.value})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
