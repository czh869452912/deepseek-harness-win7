import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source')
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/src/index.ts')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/src/index.ts')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
mkdirSync(directory,{recursive:true});const result:any[]=[]
for(const mode of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const owner=join(directory,mode);mkdirSync(owner);const source=join(owner,'plugin.mjs'),helper=join(owner,'helper.mjs')
 writeFileSync(helper,'export const value=1')
 const write=(value:number,failed=false)=>writeFileSync(source,(mode==='helper'?"import {value} from './helper.mjs';":'const value='+value+';')+
  'export default function apply(ctx,config){ctx.reloadTrace.push("start:"+value+":"+config.label);'+(failed?'throw new Error("activation failed")':'ctx.effect(()=>()=>{ctx.reloadTrace.push("stop:"+value+":"+config.label)})')+'}')
 write(1);const ctx=new Context(),trace:string[]=[];ctx.baseUrl=pathToFileURL(owner).href+'/';ctx.provide('reloadTrace',trace)
 await ctx.plugin(Loader);await ctx.plugin(Timer);await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0})
 const hmr:any=ctx.hmr,loader:any=ctx.loader,url=pathToFileURL(source).href
 try{
  if(mode==='disabled')await loader.import(url)
  const id=await loader.create({name:url,config:{label:'initial'},disabled:mode==='disabled'});await loader.await();const entry=loader.resolve(id),before=entry.fiber,namespace=entry.moduleNamespace
  if(mode==='shared'){await loader.create({name:url,config:{label:'other'}});await loader.await()}
  if(mode==='unmanaged')await ctx.plugin(loader.unwrapExports(await loader.import(url)),{label:'unmanaged'})
  if(mode==='removed'){ctx.registry.delete(loader.unwrapExports(namespace));await before.await()}
  if(mode==='config')entry.options.config={label:'latest'}
  trace.length=0;const reloaded:number[]=[];ctx.on('hmr/reload',rows=>{reloaded.push(rows.size)})
  if(mode!=='unchanged'){write(2,mode==='activation');if(mode==='syntax')writeFileSync(source,'invalid = (');if(mode==='helper')writeFileSync(helper,'export const value=2');hmr.stashed.add(pathToFileURL(mode==='helper'?helper:source).href)}
  let failed=false;try{await hmr.runExclusive(async()=>{await hmr.partialReload()})}catch{failed=true}
  result.push({mode,failed,trace:[...trace],same:entry.fiber===before,namespace_same:entry.moduleNamespace===namespace,cached_old:loader.internal.loadCache.get(url)?.module?.getNamespace()===namespace,active:entry.fiber!==undefined&&entry.fiber.uid!==null,reloaded:[...reloaded]})
  if(['syntax','activation'].includes(mode)){trace.length=0;write(3);await hmr.runExclusive(async()=>{await hmr.partialReload()});result.push({mode:mode+'-recovered',trace:[...trace],namespace_same:entry.moduleNamespace===namespace,reloaded:[...reloaded]})}
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
