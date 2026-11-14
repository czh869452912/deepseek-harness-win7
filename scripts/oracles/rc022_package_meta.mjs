import {readFileSync,writeFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {dirname,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2],input=process.argv[3]
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/lib/index.js')).href)
const {PluginPackages}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/lib/index.js')).href)
const result=[],raw=[]
for(const row of JSON.parse(readFileSync(input,'utf8'))){
 const data=row.source,ctx=new Context(),service=new PluginPackages(ctx,{resolution:data.table})
 try{
  for(const request of row.fixture.requests??['localized']){
   let value=service.metaOf(request,data.parent)??null
   raw.push({case:row.index,request,error:value?.error??null})
   if(value!==null){
    value={...value}
    if('error' in value)value.error=true
    if('icon' in value){const [header,encoded]=value.icon.split(','),data=Buffer.from(encoded,'base64');value.icon={header,bytes:data.length,sha256:createHash('sha256').update(data).digest('hex')}}
   }
   result.push({case:row.index,request,value})
  }
 }finally{await ctx.fiber.dispose()}
}
writeFileSync(resolve(dirname(input),'source-diagnostics.json'),JSON.stringify(raw))
process.stdout.write(JSON.stringify(result))
