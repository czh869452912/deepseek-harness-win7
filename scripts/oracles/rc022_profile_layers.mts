import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,relative,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!,load=(path:string)=>import(pathToFileURL(resolve(root,path)).href)
const {loadProfileDirectory,composeEntries,reportSkippedBundles}=await load('packages/boot/app-boot/src/profile.ts')
const {assertBundlePlatform}=await load('packages/boot/app-boot/src/bundle-platform.ts'),result:any[]=[]
function fixture(directory:string,mode:string){
 const app=join(directory,'app'),profile=join(directory,'profile');mkdirSync(app,{recursive:true});mkdirSync(profile)
 writeFileSync(join(app,'package.json'),'{}')
 const selected=['multi','missing','bad-paths','broken','not-bundle','restricted','bad-platforms','guarded','kept']
 for(const name of selected){
  if(name==='missing')continue
  const path=join(app,'node_modules',name);mkdirSync(path,{recursive:true})
  const bundle:any={patch:'./patch.yml'}
  if(name==='multi')bundle.patch=['./first.yml','./layers/second.yml']
  if(name==='bad-paths')bundle.patch=[1]
  if(name==='restricted')bundle.platforms=[process.platform==='darwin'?'win32':'darwin']
  if(name==='bad-platforms')bundle.platforms=[]
  const manifest:any={name,version:'1.0.0',dsh:{bundle}}
  if(name==='not-bundle')delete manifest.dsh
  if(name==='guarded')manifest.engines={dsh:'^99'}
  writeFileSync(join(path,'package.json'),JSON.stringify(manifest))
  writeFileSync(join(path,'patch.yml'),name==='broken'?'[':JSON.stringify([{insert:[{id:name,name:'cordis:group'}]}]))
  if(name==='multi'){
   mkdirSync(join(path,'layers'));writeFileSync(join(path,'first.yml'),JSON.stringify([{insert:[{id:'first',name:'./local.mjs',config:{value:1}}]}]))
   writeFileSync(join(path,'layers/second.yml'),JSON.stringify([{id:'first',config:{value:2}},{insert:[{id:'second',name:'./local.mjs'}]}]))
  }
 }
 if(mode==='retired')selected.push('@deepseek-ai/dsh-experimental-schedule-bundle','@deepseek-ai/dsh-experimental-agent-team-profile')
 writeFileSync(join(profile,'package.json'),JSON.stringify({name:'profile',preserved:'yes',dsh:{profile:{bundles:selected}}}))
 writeFileSync(join(profile,'cordis.patch.yml'),['user-broken','bundles-only'].includes(mode)?'[':JSON.stringify([{id:'first',config:{value:3}}]))
 writeFileSync(join(profile,'compatibility.json'),JSON.stringify(mode==='grant'?{'guarded@1.0.0':['0.2.2-rc.3']}:{}))
 return {anchor:join(app,'package.json'),profile}
}
for(const mode of JSON.parse(readFileSync(input,'utf8'))){
 const directory=resolve(dirname(input),'files/source',mode),{anchor,profile}=fixture(directory,mode),before=readFileSync(join(profile,'package.json'),'hex')
 let loaded:any,error=false,warning='';const write=process.stderr.write;process.stderr.write=((chunk:any)=>{warning+=String(chunk);return true}) as any
 try{loaded=loadProfileDirectory('probe',profile,anchor,{userLayer:mode!=='bundles-only'})}catch{error=true}finally{process.stderr.write=write}
 const row:any={mode,error,silent:warning==='',manifest:JSON.parse(readFileSync(join(profile,'package.json'),'utf8')),unchanged:before===readFileSync(join(profile,'package.json'),'hex')}
 if(loaded){
  let report='';process.stderr.write=((chunk:any)=>{report+=String(chunk);return true}) as any
  try{reportSkippedBundles('probe',loaded)}finally{process.stderr.write=write}
  Object.assign(row,{layers:loaded.layers.map((layer:any)=>({name:layer.packageName,paths:layer.patchPaths.map((p:string)=>relative(directory,p).split('\\').join('/'))})),skipped:loaded.skippedBundles.map((s:any)=>s.packageName),reasons:Object.fromEntries(loaded.skippedBundles.map((s:any)=>[s.packageName,['cannot resolve profile bundle','file path or a list','failed to parse','declares no dsh.bundle','Host is running','nonempty list','incompatible with dsh'].find(value=>s.reason.includes(value))??'other'])),entries:composeEntries([...loaded.layers.map((layer:any)=>layer.patches),loaded.patches]),report_lines:report.trim().split('\n').length})
  for(const entry of row.entries)if(entry.name.startsWith('file:'))entry.name=entry.name.replace(pathToFileURL(directory).href,'$ROOT')
 }
 result.push(row)
}
for(const platforms of [null,[],['wsl'],['linux'],['win32'],['bogus'],'win32',['wsl','darwin']])for(const platform of ['win32','linux','darwin'])for(const marker of [false,true]){
 let error=null
 try{assertBundlePlatform(platforms,platform,{env:marker?{WSL_INTEROP:'yes'}:{},osRelease:'generic'})}catch(e){error=(e as Error).message}
 result.push({platforms,platform,marker,error})
}
process.stdout.write(JSON.stringify(result))
