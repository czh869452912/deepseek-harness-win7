import {mkdirSync,readFileSync,symlinkSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source')
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/lib/index.js')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/lib/index.js')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/lib/index.js')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/lib/index.js')).href)
const sleep=(ms:number)=>new Promise<void>(done=>setTimeout(done,ms))
mkdirSync(directory,{recursive:true});const result:any[]=[]
for(const mode of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const owner=join(directory,mode),pkg=join(owner,'addon');mkdirSync(pkg,{recursive:true});mkdirSync(join(owner,'node_modules'));symlinkSync(pkg,join(owner,'node_modules/addon'),'junction')
 const manifest=join(pkg,'package.json'),mapping=(name:string)=>writeFileSync(manifest,JSON.stringify({name:'addon',version:'1.0.0',exports:'./'+name+'.mjs'}))
 const write=(name:string,value:string)=>writeFileSync(join(pkg,name+'.mjs'),'export default function apply(ctx,config){const trace=ctx.reloadTrace;trace.push("start:'+value+':"+config.label);ctx.effect(()=>()=>{trace.push("stop:'+value+':"+config.label)})}')
 mapping('a');write('a','a');write('b','b');const ctx=new Context(),trace:string[]=[];ctx.baseUrl=pathToFileURL(owner).href+'/';ctx.provide('reloadTrace',trace)
 await ctx.plugin(Loader);await ctx.plugin(Timer);await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0});const loader:any=ctx.loader,hmr:any=ctx.hmr
 try{
  const first=loader.resolve(await loader.create({name:'addon',config:{label:'one'}}));await loader.await();const oldFirst=first.moduleNamespace;let shadow:any
  if(['disabled-shadow','duplicate-shadow'].includes(mode)){if(mode==='duplicate-shadow')await loader.create({name:'addon',config:{label:'duplicate'}});shadow=loader.resolve(await loader.create({name:'addon',disabled:true}));await loader.await()}
  if(mode==='disabled-reenable'){await first.update({disabled:true});await loader.await()}
  trace.length=0;mapping('b');hmr.watcher.emit('change',manifest);await sleep(40);await hmr.runExclusive(async()=>{});result.push({mode,step:'mapping',trace:[...trace],first_same:first.moduleNamespace===oldFirst})
  let second:any;if(mode==='two-active'){second=loader.resolve(await loader.create({name:'addon',config:{label:'two'}}));await loader.await()}const oldSecond=second?.moduleNamespace
  trace.length=0;write('a','a-edited');hmr.stashed.add(pathToFileURL(join(pkg,'a.mjs')).href);await hmr.runExclusive(async()=>{await hmr.partialReload()});result.push({mode,step:'old-source',trace:[...trace],first_same:first.moduleNamespace===oldFirst,second_same:second===undefined||second.moduleNamespace===oldSecond,shadow_inactive:shadow===undefined||shadow.fiber===undefined})
  if(second!==undefined){trace.length=0;write('b','b-edited');hmr.stashed.add(pathToFileURL(join(pkg,'b.mjs')).href);await hmr.runExclusive(async()=>{await hmr.partialReload()});result.push({mode,step:'new-source',trace:[...trace],shared:first.fiber.runtime===second.fiber.runtime})}
  if(mode==='disabled-reenable'){trace.length=0;await first.update({disabled:false});await loader.await();result.push({mode,step:'reenable',trace:[...trace]})}
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
