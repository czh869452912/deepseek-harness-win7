import {readFileSync,writeFileSync} from 'node:fs'
import {dirname,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2],input=process.argv[3]
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/lib/index.js')).href)
const {PluginPackages,prepareProfileEntries}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/lib/index.js')).href)
const result=[],raw=[]
for(const {index:caseIndex,source:data} of JSON.parse(readFileSync(input,'utf8'))){
 const ctx=new Context();new PluginPackages(ctx,{resolution:data.table})
 ctx.provide('profileContext',{dir:data.table.profileDir})
 try{
  const caller=await import(data.parent)
  for(const [index,request] of data.requests.entries()){
   let value=null,code=null
   const admitted=prepareProfileEntries(ctx,[{id:'entry',name:request}],data.parent)
   try{value=(await caller.load(request)).value}catch(error){code=error.code??error.name;raw.push({case:caseIndex,request,error:String(error)})}
   result.push({case:caseIndex,request:index,value,code,disabled:admitted[0].disabled??false})
  }
 }finally{await ctx.fiber.dispose()}
}
writeFileSync(resolve(dirname(input),'source-diagnostics.json'),JSON.stringify(raw))
process.stdout.write(JSON.stringify(result))
