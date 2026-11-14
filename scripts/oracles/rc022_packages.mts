import {mkdirSync,writeFileSync,renameSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const root=process.argv[2]!,input=process.argv[3]!,spec=JSON.parse(readFileSync(input,'utf8'))
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const {PluginPackages}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/profile-resolution/service.ts')).href)
const {barePackageName,ResolutionRestartRequired}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/profile-resolution/resolver.ts')).href)
function pkg(path:string,name:string,fields:any={}){mkdirSync(path,{recursive:true});writeFileSync(join(path,'package.json'),JSON.stringify({name,version:'1.0.0',...fields}))}
function fixture(base:string,mode:string){
 const active=join(base,'profiles/active');mkdirSync(active,{recursive:true})
 const entry={name:'core',packageDir:join(base,'installation/node_modules/core'),declarer:join(base,'installation/package.json'),version:'1.0.0',scope:'installation'}
 const privateEntry={name:'private',packageDir:join(base,'selected/node_modules/private'),declarer:join(base,'selected/package.json'),version:'1.0.0',scope:'profile'}
 for(const row of [entry,privateEntry])pkg(row.packageDir,row.name)
 pkg(join(base,'node_modules/absent'),'fallback')
 const table:any={profilesDir:join(base,'profiles'),profileDir:active,localPackageNames:[],entries:[entry,privateEntry],linkedRoots:[]}
 let parent=join(active,'caller.mjs')
 if(['native','linked-unlisted'].includes(mode))parent=join(base,'outside/caller.mjs')
 if(mode==='sibling')parent=join(base,'profiles/sibling/caller.mjs')
 if(mode==='outside-profile'){table.profileDir=join(base,'custom');parent=join(base,'custom/caller.mjs')}
 if(['nested','local-empty','self','invalid'].includes(mode)){
  const owner=join(active,'node_modules/owner');pkg(owner,mode==='self'?'core':'owner',mode==='self'?{exports:'./index.mjs'}:{})
  parent=join(owner,'caller.mjs')
  if(mode==='nested')pkg(join(owner,'node_modules/core'),'nested')
  if(mode==='local-empty')mkdirSync(join(owner,'node_modules/core'),{recursive:true})
  if(mode==='invalid')writeFileSync(join(owner,'package.json'),'{')
 }
 if(mode==='declared-local'){table.localPackageNames=['core'];pkg(join(active,'node_modules/core'),'direct')}
 if(mode.startsWith('linked-')||mode==='installation-overlap'){
  const linked=join(base,'external');pkg(linked,'external',{peerDependencies:{core:'*'}})
  table.linkedRoots=[{name:'external',realPath:linked}];parent=join(linked,'caller.mjs')
  if(['linked-peer','linked-local'].includes(mode))pkg(join(linked,'node_modules/core'),'physical-peer')
  if(mode==='linked-local')pkg(linked,'external')
  if(mode==='linked-deep'){parent=join(linked,'nested/caller.mjs');pkg(join(linked,'nested/node_modules/core'),'deep')}
  if(mode==='linked-unlisted')table.entries=[]
  if(mode==='installation-overlap'){entry.packageDir=linked;pkg(join(linked,'node_modules/core'),'own-installation')}
 }
 if(mode==='cache-absence'){renameSync(entry.packageDir,join(base,'empty-old'));mkdirSync(entry.packageDir)}
 return {table,parent:pathToFileURL(parent).href}
}
function successor(table:any,mode:string){
 const value=structuredClone(table)
 if(mode.startsWith('profile-')&&mode!=='profile-dir'){
  const row=value.entries[1],field=mode.slice('profile-'.length)
  if(field==='remove')value.entries.pop();else if(field==='move')row.packageDir+='-moved';else if(field==='declarer')row.declarer+='-changed';else if(field==='version')row.version='2.0.0'
 }else if(mode.startsWith('installation-')){
  const row=value.entries[0],field=mode.slice('installation-'.length)
  if(field==='remove')value.entries.shift();else if(field==='move')row.packageDir+='-moved';else if(field==='declarer')row.declarer+='-changed';else if(field==='version')row.version='2.0.0'
 }else if(mode==='scope')value.entries[1].scope='installation'
 else if(mode==='local-add')value.localPackageNames=['core','private']
 else if(mode==='local-remove')value.localPackageNames=[]
 else if(mode==='new')value.entries.push({...value.entries[1],name:'new'})
 else if(mode==='profiles-dir')value.profilesDir+='-changed'
 else if(mode==='profile-dir')value.profileDir+='-changed'
 return value
}
const result:any[]=spec.requests.map((request:string)=>({request,name:barePackageName(request)??null}))
for(const mode of spec.modes){
 const base=resolve(dirname(input),'files/source',mode),{table,parent}=fixture(base,mode),ctx=new Context(),service=new PluginPackages(ctx,mode==='native'?{}:{resolution:table})
 const row:any={mode,packages:{}}
 try{
  for(const name of ['core','core/feature','private','absent'])row.packages[name]=service.packageOf(name,parent)??null
  const first=service.packageOf('core',parent);row.shared=first===service.packageOf('core/other',parent)
  if(['cache','cache-absence'].includes(mode)){
   pkg(table.entries[0].packageDir,'edited');row.cached=service.packageOf('core',parent)??null
   service.replace(structuredClone(table));row.replacement=service.packageOf('core',parent)??null
  }
 }finally{await ctx.fiber.dispose()}
 result.push(JSON.parse(JSON.stringify(row).replaceAll(JSON.stringify(base).slice(1,-1),'$ROOT')))
}
for(const mode of spec.replacements){
 const base=resolve(dirname(input),'files/source','replace-'+mode),{table,parent}=fixture(base,'active')
 if(mode==='local-remove')table.localPackageNames=['core']
 const ctx=new Context(),service=new PluginPackages(ctx,{resolution:table}),first=service.packageOf('core',parent),next=successor(table,mode)
 let error:string|null=null,restart=false
 try{service.replace(next)}catch(failure){error=(failure as Error).message;restart=failure instanceof ResolutionRestartRequired}
 result.push({mode:'replace-'+mode,error,restart,published:service.resolution===next,same_cache:service.packageOf('core',parent)===first})
 await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(result))
