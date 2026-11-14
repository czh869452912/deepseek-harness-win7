/** Exercise the unchanged upstream atomic writer on real owned files. */
import {mkdir,readFile,writeFile,rm,readdir} from 'node:fs/promises'
import {dirname,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/context.ts')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/src/index.ts')).href)
const {default:Include}=await import(pathToFileURL(resolve(root,'vendor/include/src/index.ts')).href)
const output=resolve(dirname(input),'files/source');await mkdir(output,{recursive:true})
const result:any[]=[]
for(const [index,c] of JSON.parse(await readFile(input,'utf8')).entries()){
  const path=resolve(output,`${index}.json`);await writeFile(path,c.initial)
  const ctx=new Context();ctx.baseUrl=pathToFileURL(output).href+'/'
  await ctx.plugin(Loader);const include=new Include(ctx,{path:pathToFileURL(path).href})
  if(c.mode==='missing')await rm(path)
  else if(c.mode==='stale')await writeFile(path,'["external"]')
  let error=null
  try{if(c.mode==='unconditional')await include._writeText(c.new);else await include._writeText(c.new,c.initial)}catch(reason:any){error=reason.name}
  const content=await readFile(path,'utf8').catch((reason:any)=>{if(reason.code==='ENOENT')return null;throw reason})
  result.push([error,content,(await readdir(output)).filter(name=>name.startsWith('.')&&name.endsWith('.tmp')).length])
  await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(result))
