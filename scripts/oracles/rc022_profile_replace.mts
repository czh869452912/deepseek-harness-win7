import fs from 'node:fs'
import {syncBuiltinESMExports} from 'node:module'
import {dirname,join,relative,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {initializeProfileFromDefault}=await import(pathToFileURL(resolve(root,'apps/cli/src/profile-boot.ts')).href)
const {initProfile}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/profile.ts')).href)
function snapshot(home:string){
 const result:Record<string,unknown>={}
 function walk(path:string){for(const entry of fs.readdirSync(path,{withFileTypes:true})){
  const file=join(path,entry.name)
  if(entry.isDirectory())walk(file)
  else if(entry.isFile()){
   const name=relative(home,file).replaceAll('\\','/').replace(/\.rescue\.staging-[^/]+/g,'.rescue.staging-$ID'),text=fs.readFileSync(file,'utf8').replaceAll('\r\n','\n')
   result[name]=entry.name==='package.json'?JSON.parse(text):text
  }
 }}walk(home);return result
}
function category(error:any){
 if(error===null)return null
 for(const [marker,value] of [['could not be restored','restore'],['was recreated concurrently','concurrent'],['unknown default profile','unknown'],['names shipped profile','shipped'],['invalid profile','invalid'],['injected','injected']])if(String(error).includes(marker!))return value
 return error.name
}
const result:any[]=[],raw:any[]=[]
for(const [index,entry] of JSON.parse(fs.readFileSync(input,'utf8')).entries()){
 const home=resolve(dirname(input),'files/source',String(index)),name=entry.name??'rescue',mode=entry.mode??'new',dir=join(home,'profiles',name)
 fs.mkdirSync(home,{recursive:true})
 if(!['new','write'].includes(mode)){
  fs.mkdirSync(dir,{recursive:true});if(mode!=='residual')initProfile(dir,['old-bundle'])
  fs.writeFileSync(join(dir,'old-marker'),'old')
 }
 const rename=fs.renameSync,remove=fs.rmSync,write=fs.writeFileSync,stderr=process.stderr.write
 let error:any=null,warning=''
 fs.renameSync=((from:any,to:any)=>{
  if(mode==='old-rename'&&from===dir)throw new Error('injected old rename')
  if(to===dir&&(mode==='restore'||mode==='new-rename'&&from.endsWith(join('new',name))))throw new Error('injected rename')
  if(mode==='concurrent'&&from.endsWith(join('new',name)))initProfile(dir,['concurrent-bundle'])
  rename(from,to)
 }) as typeof rename
 fs.rmSync=((path:any,options:any)=>{if(mode==='cleanup'&&String(path).includes('.staging-'))throw new Error('injected cleanup');remove(path,options)}) as typeof remove
 fs.writeFileSync=((...args:any[])=>{if(mode==='write'&&String(args[0]).endsWith(join('new',name,'package.json')))throw new Error('injected write');Reflect.apply(write,fs,args)}) as typeof write
 process.stderr.write=((value:any)=>{warning+=String(value);return true}) as typeof stderr
 syncBuiltinESMExports()
 try{initializeProfileFromDefault(name,entry.template??'web',home);if(mode==='twice')initializeProfileFromDefault(name,'headless',home)}catch(failure){error=failure}
 finally{fs.renameSync=rename;fs.rmSync=remove;fs.writeFileSync=write;process.stderr.write=stderr;syncBuiltinESMExports()}
 result.push({case:index,error:category(error),members:error?.errors?.length??0,warning:warning.length>0,files:snapshot(home)})
 raw.push({case:index,error:error===null?null:String(error),warning})
}
fs.writeFileSync(resolve(dirname(input),'source-diagnostics.json'),JSON.stringify(raw))
process.stdout.write(JSON.stringify(result))
