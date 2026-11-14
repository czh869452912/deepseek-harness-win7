import {mkdirSync,writeFileSync,unlinkSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!, directory=resolve(dirname(process.argv[3]!),'files/source')
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/src/index.ts')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/src/index.ts')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
mkdirSync(directory,{recursive:true})
const result:any[]=[]
async function fixture(name:string){
 const owner=join(directory,name);mkdirSync(owner)
 const ctx=new Context();ctx.baseUrl=pathToFileURL(owner).href+'/'
 await ctx.plugin(Loader);await ctx.plugin(Timer)
 await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0,awaitWriteFinish:false})
 return {ctx,hmr:ctx.hmr,owner}
}
const tick=()=>new Promise<void>(done=>setImmediate(done))
{
 const {ctx,hmr}=await fixture('serial'),release=Promise.withResolvers<void>(),entered=Promise.withResolvers<void>(),order:string[]=[]
 try{
  const first=hmr.runExclusive(async()=>{order.push('first');entered.resolve();await release.promise;throw new Error('mutation failed')})
  const failed=first.catch((error:Error)=>error.message)
  await entered.promise
  const next=hmr.runExclusive(async()=>{order.push('second');try{await hmr.runExclusive(async()=>{})}catch(error){order.push((error as Error).message)}return 42})
  const before=[...order];release.resolve()
  result.push({case:'failure-and-nesting',before,order,reason:await failed,value:await next})
 }finally{release.resolve();await ctx.fiber.dispose()}
}
{
 const {ctx,hmr,owner}=await fixture('watch'),release=Promise.withResolvers<void>(),entered=Promise.withResolvers<void>(),refreshed=Promise.withResolvers<void>(),order:string[]=[]
 try{
  const job=hmr.runExclusive(async()=>{entered.resolve();await release.promise;order.push('write')});await entered.promise
  const filename=join(owner,'config.json');writeFileSync(filename,'{}')
  const refresh=async()=>{order.push('refresh');refreshed.resolve()}
  const dispose=await hmr.watchConfig(filename,refresh);let duplicate=false
  try{await hmr.watchConfig(filename,refresh)}catch{duplicate=true}
  await tick();const before=[...order];release.resolve();await job;await refreshed.promise;await dispose()
  const again=await hmr.watchConfig(join(owner,'missing.json'),refresh);await hmr.runExclusive(async()=>{await again()})
  result.push({case:'watch-queue-and-dispose',before,order,duplicate})
 }finally{release.resolve();await ctx.fiber.dispose()}
}
{
 const {ctx,hmr,owner}=await fixture('register-in-transaction'),order:string[]=[],refreshed=Promise.withResolvers<void>()
 const filename=join(owner,'config.json');writeFileSync(filename,'{}')
 try{
  const dispose=await hmr.runExclusive(async()=>{const dispose=await hmr.watchConfig(filename,async()=>{order.push('refresh');refreshed.resolve()});order.push('registered');return dispose})
  await refreshed.promise;await dispose();result.push({case:'watch-exits-transaction-context',order})
 }finally{await ctx.fiber.dispose()}
}
{
 const {ctx,hmr,owner}=await fixture('drain-watch'),release=Promise.withResolvers<void>(),entered=Promise.withResolvers<void>(),order:string[]=[]
 const filename=join(owner,'config.json');writeFileSync(filename,'{}')
 try{
  const dispose=await hmr.watchConfig(filename,async()=>{entered.resolve();await release.promise;order.push('refresh-completed')});await entered.promise
  const closing=dispose().then(()=>{order.push('disposed')});await tick();const before=[...order]
  release.resolve();await closing;result.push({case:'external-watch-drains',before,order})
 }finally{release.resolve();await ctx.fiber.dispose()}
}
{
 const {ctx,hmr}=await fixture('self-dispose')
 try{await hmr.runExclusive(async()=>{await ctx.fiber.dispose()});try{await hmr.runExclusive(async()=>{})}catch(error){result.push({case:'self-dispose',reason:(error as Error).message})}}
 finally{await ctx.fiber.dispose()}
}
{
 const {ctx,hmr}=await fixture('drain-owner'),release=Promise.withResolvers<void>(),entered=Promise.withResolvers<void>(),order:string[]=[]
 try{
  const job=hmr.runExclusive(async()=>{entered.resolve();await release.promise;order.push('mutation-completed')});await entered.promise
  const closing=ctx.fiber.dispose().then(()=>{order.push('disposed')});await tick();const before=[...order]
  release.resolve();await job;await closing;result.push({case:'external-owner-drains',before,order})
 }finally{release.resolve();await ctx.fiber.dispose()}
}
{
 const {ctx,hmr,owner}=await fixture('start-failure'),filename=join(owner,'parent/config.json');writeFileSync(dirname(filename),'file')
 try{
  let failed=false;try{await hmr.watchConfig(filename,async()=>{})}catch{failed=true}
  unlinkSync(dirname(filename));mkdirSync(dirname(filename));const dispose=await hmr.watchConfig(filename,async()=>{});await dispose()
  result.push({case:'failed-start-releases-path',failed,retry:true})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
