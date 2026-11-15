import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve,relative} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source')
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/src/index.ts')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/src/index.ts')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
mkdirSync(directory,{recursive:true});const result:any[]=[]
for(const mode of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const owner=join(directory,mode);mkdirSync(owner);const helper=join(owner,'helper.mjs'),first=join(owner,'first.mjs'),second=join(owner,mode==='retained-installed'?'node_modules/retained/second.mjs':'second.mjs');mkdirSync(dirname(second),{recursive:true})
 const write=(value:number)=>writeFileSync(helper,['shared','left','right'].map(name=>'export function '+name+'(ctx,config){const trace=ctx.reloadTrace;trace.push("start:'+name+':'+value+':"+config.label);ctx.effect(()=>()=>{trace.push("stop:'+name+':'+value+':"+config.label)})}').join('\n'))
 const alias=(file:string,name:string)=>writeFileSync(file,'export {'+name+' as default} from '+JSON.stringify('./'+relative(dirname(file),helper).replaceAll('\\','/')))
 write(1);alias(first,'shared');alias(second,'shared');const ctx=new Context(),trace:string[]=[];ctx.baseUrl=pathToFileURL(owner).href+'/';ctx.provide('reloadTrace',trace)
 await ctx.plugin(Loader);await ctx.plugin(Timer);await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0});const loader:any=ctx.loader,hmr:any=ctx.hmr
 try{
  const ids=[];for(const [file,label] of [[first,'one'],[second,'two']])ids.push(await loader.create({name:pathToFileURL(file!).href,config:{label}}));await loader.await()
  const entries=ids.map(id=>loader.resolve(id)),before=entries.map(entry=>entry.moduleNamespace)
  if(mode==='split-unmanaged')await ctx.plugin(loader.unwrapExports(before[0]),{label:'unmanaged'})
  trace.length=0;const events:number[]=[];ctx.on('hmr/reload',rows=>{events.push(rows.size)});write(2)
  if(mode.startsWith('split')){alias(first,'left');alias(second,'right')}
  hmr.stashed.add(pathToFileURL(helper).href);let failed=false
  try{await hmr.runExclusive(async()=>{await hmr.partialReload()})}catch(error){if(!(error as Error).message.includes('ambiguous'))throw error;failed=true}
  result.push({mode,failed,trace:[...trace],namespace_same:entries.map((entry,index)=>entry.moduleNamespace===before[index]),shared:entries[0].fiber.runtime===entries[1].fiber.runtime,events,cached_same:[first,second].map((file,index)=>loader.internal.loadCache.get(pathToFileURL(file).href)?.module?.getNamespace()===before[index]),old_instances:[...ctx.registry.get(loader.unwrapExports(before[0]))?.fibers??[]].length})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
