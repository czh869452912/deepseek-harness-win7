import {mkdirSync,writeFileSync} from 'node:fs'
import {basename,dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source')
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/src/index.ts')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/src/index.ts')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
const {default:Include}=await import(pathToFileURL(resolve(root,'vendor/include/src/index.ts')).href)
const sleep=(ms:number)=>new Promise<void>(done=>setTimeout(done,ms))
mkdirSync(directory,{recursive:true});const result:any[]=[]
for(const mode of ['unrelated','includes','full','exact','failure','queued']){
 const owner=join(directory,mode);mkdirSync(owner);const ctx=new Context();ctx.baseUrl=pathToFileURL(owner).href+'/'
 await ctx.plugin(Loader);await ctx.plugin(Timer);await ctx.plugin(Hmr,{root:[],ignored:[],debounce:10,awaitWriteFinish:false})
 const hmr:any=ctx.hmr,loader:any=ctx.loader,trace:string[]=[],invalidated:string[]=[],release=Promise.withResolvers<void>();let before:string[]|undefined
 const cache=new Map();hmr.internal={loadCache:cache}
 ctx.on('hmr/change',(url:string)=>{trace.push('change:'+basename(url))})
 const originalWait=loader.await.bind(loader);loader.await=async()=>{trace.push('await');await originalWait()};loader.exit=()=>{trace.push('exit')}
 let partialCount=0;hmr.partialReload=async()=>{partialCount++;trace.push('partial:'+([...hmr.stashed] as string[]).map(url=>basename(url)).sort().join(','));if(mode==='failure'&&partialCount===1)throw new Error('replacement failed')}
 hmr.manifests.invalidate=(filename:string)=>{invalidated.push(basename(filename))}
 const emit=(...files:string[])=>{for(const file of files)hmr.watcher.emit('change',file)}
 const drain=async()=>{await sleep(50);await hmr.runExclusive(async()=>{})}
 try{
  if(mode==='unrelated'){emit('package.json.lock','package.json','note.txt','note.txt');await drain()}
  else if(['includes','full','queued'].includes(mode)){
   loader.builtins.include=Include
   for(const name of ['first.yml','second.yml']){
    writeFileSync(join(owner,name),'[]');const id=await loader.create({name:'cordis:include',config:{path:pathToFileURL(join(owner,name)).href}});await originalWait()
    const include=loader.resolve(id).subtree,refresh=include.refresh.bind(include);include.refresh=async()=>{trace.push('refresh:'+name);if(mode==='includes'&&name==='first.yml')throw new Error('unsaved runtime change');await refresh()}
   }
   cache.set(pathToFileURL(join(owner,'cached.js')).href,undefined)
   if(mode==='full'){hmr.externals.add(pathToFileURL(join(owner,'framework.js')).href);emit('first.yml','cached.js','framework.js','note.txt')}
   else if(mode==='queued'){
    const entered=Promise.withResolvers<void>();const job=hmr.runExclusive(async()=>{entered.resolve();await release.promise;trace.push('write')});await entered.promise
    emit('first.yml','cached.js','first.yml','second.yml');await sleep(50);before=[...trace];release.resolve();await job
   }else emit('first.yml','first.yml','second.yml')
   await drain()
  }else if(mode==='exact'){
   const dispose=await hmr.watchConfig(join(owner,'missing.yml'),async()=>{trace.push('exact')});emit('missing.yml','note.txt');await drain();await dispose()
  }else{
   cache.set(pathToFileURL(join(owner,'cached.js')).href,undefined);emit('cached.js');await drain();emit('cached.js');await drain()
  }
  result.push({case:mode,trace,invalidated,stashed:hmr.stashed.size,...(mode==='queued'?{before}:{})})
 }finally{release.resolve();await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
