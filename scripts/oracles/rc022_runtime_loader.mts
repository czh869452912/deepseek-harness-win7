import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const {PluginPackages}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/profile-resolution/service.ts')).href)
const result:any[]=[]
for(const {mode,source:{table,parent}} of JSON.parse(readFileSync(input,'utf8'))){
 const ctx=new Context(),service=new PluginPackages(ctx,{resolution:table})
 try{
  const caller=await import(parent)
  for(const name of ['core','private','absent']){
   let value:any=null,error=false
   try{value=(await caller.load(name)).value}catch{error=true}
   const metadata=service.packageOf(name,parent)
   result.push({mode,name,value,error,metadata:metadata?.name??null})
  }
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
