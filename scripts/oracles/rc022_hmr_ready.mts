import {mkdirSync,writeFileSync,symlinkSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!, directory=resolve(dirname(process.argv[3]!),'files/source')
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/src/index.ts')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/src/index.ts')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
mkdirSync(directory,{recursive:true})
const result:any[]=[],tick=()=>new Promise<void>(done=>setImmediate(done))
async function fixture(name:string,ready=true){
 const owner=join(directory,name),profile=join(owner,'profile');mkdirSync(profile,{recursive:true})
 const ctx=new Context();ctx.baseUrl=pathToFileURL(profile).href+'/'
 await ctx.plugin(Loader);await ctx.plugin(Timer)
 ctx.provide('profileContext',{dir:profile,home:owner,patchPath:join(profile,'patch.json'),startedBundles:[]})
 let listener:(()=>void)|undefined
 if(ready)ctx.provide('appReady',{onReady(callback:()=>void){listener=callback;return ()=>{listener=undefined}}})
 return {ctx,profile,commit:()=>listener?.()}
}
{
 const {ctx}=await fixture('missing',false)
 try{try{await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0})}catch(error){result.push({case:'requires-ready',rejected:String(error).includes('Profile HMR requires application readiness')})}}
 finally{await ctx.fiber.dispose()}
}
for(const mode of ['commit','cancel','baseline-error']){
 const {ctx,profile,commit}=await fixture(mode);await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0,awaitWriteFinish:false})
 const hmr:any=ctx.hmr,filename=join(profile,'watched.json');writeFileSync(filename,'{}')
 const called:string[]=[],completed=Promise.withResolvers<void>()
 try{
  const mutation=await hmr.runExclusive(async()=>42),dispose=await hmr.watchConfig(filename,async()=>{called.push('refresh');completed.resolve()})
  await tick();const before=[...called]
  if(mode==='cancel'){await ctx.fiber.dispose();commit()}
  else{
   if(mode==='baseline-error')hmr.files.observe=()=>{throw new Error('observation failed')}
   commit();await completed.promise;await dispose()
  }
  result.push({case:mode,mutation,before,after:called})
 }finally{await ctx.fiber.dispose()}
}
{
 const {ctx,profile,commit}=await fixture('baseline'),outside=join(dirname(profile),'linked'),modules=join(profile,'node_modules/@scope')
 mkdirSync(outside);mkdirSync(modules,{recursive:true});symlinkSync(outside,join(modules,'linked'),'junction')
 const ordinary=join(modules,'ordinary');mkdirSync(ordinary)
 const paths=[join(profile,'local.py'),join(outside,'linked.py'),join(dirname(profile),'sibling.py'),join(ordinary,'nested.py')]
 const cache=ctx.loader.internal!.loadCache
 try{
  for(const path of paths){writeFileSync(path,'pass\n');Map.prototype.set.call(cache,pathToFileURL(path).href,{})}
  await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0,awaitWriteFinish:false});commit()
  const stale=(ctx.hmr as any).files.compare(paths.map(path=>pathToFileURL(path).href)).stale
  result.push({case:'initial-profile-and-linked-records',stale:paths.filter(path=>stale.has(pathToFileURL(path).href)).map(path=>path.split(/[\\/]/).at(-1))})
 }finally{for(const path of paths)Map.prototype.delete.call(cache,pathToFileURL(path).href);await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
