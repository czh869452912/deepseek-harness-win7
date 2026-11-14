import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2],input=process.argv[3]
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/lib/index.js')).href)
const {PluginPackages,resolvePluginResource}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/lib/index.js')).href)
function pkg(path,name,fields={}){mkdirSync(path,{recursive:true});writeFileSync(join(path,'package.json'),JSON.stringify({name,version:'1.0.0',...fields}));return join(path,'package.json')}
function fixture(directory,entry){
 const active=join(directory,'profiles/active'),anchor=pkg(join(directory,'installation'),'installation'),library=join(dirname(anchor),'node_modules/lib')
 const fields=entry.mode==='legacy'?{main:'./root.json'}:{exports:['exports','self'].includes(entry.mode)?entry.value:{'.':'./root.json','./feature':'./feature.json','./item':'./item.json'}}
 pkg(library,'lib',fields);pkg(active,'caller',entry.mode==='imports'?{imports:entry.value}:{})
 if(entry.mode==='self')pkg(active,'lib',{exports:entry.value})
 for(const path of [active,library]){
  for(const name of ['root','feature','node','import','default','browser','exact','item'])writeFileSync(join(path,name+'.json'),'{}')
  for(const sub of ['wild/feature','wild/other','wild/a%2fb','wild/exact','specific/item','specific/exact']){const file=join(path,sub+'.json');mkdirSync(dirname(file),{recursive:true});writeFileSync(file,'{}')}
  mkdirSync(join(path,'folder'))
 }
 return {table:{profilesDir:join(directory,'profiles'),profileDir:active,entries:[{name:'lib',packageDir:library,declarer:anchor,version:'1.0.0',scope:'installation'}],localPackageNames:[],linkedRoots:[]},parent:pathToFileURL(join(active,'caller.mjs')).href}
}
const result=[],raw=[]
for(const [index,entry] of JSON.parse(readFileSync(input,'utf8')).entries()){
 const directory=resolve(dirname(input),'files/source',String(index)),{table,parent}=fixture(directory,entry),ctx=new Context()
 new PluginPackages(ctx,{resolution:table})
 try{
  for(const request of entry.requests){
   let path=null,code=null,error=null
   try{path=resolvePluginResource(request,parent).replaceAll(directory,'$ROOT')}catch(failure){code=(failure).code??(failure).name;error=String(failure)}
   result.push({index,request,path,code});raw.push({index,request,error})
  }
 }finally{await ctx.fiber.dispose()}
}
writeFileSync(resolve(dirname(input),'source-diagnostics.json'),JSON.stringify(raw))
process.stdout.write(JSON.stringify(result))
