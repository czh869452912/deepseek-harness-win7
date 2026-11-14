import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,relative,resolve,sep} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!,directory=resolve(dirname(input),'files/source')
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/src/index.ts')).href)
mkdirSync(join(directory,'package/nested'),{recursive:true});writeFileSync(join(directory,'package/package.json'),'{}');writeFileSync(join(directory,'package/nested/package.json'),'{}')
const urls=Array.from({length:6},(_,index)=>pathToFileURL(join(directory,`package/nested/${index}.py`)).href),result:any[]=[]
for(const row of JSON.parse(readFileSync(input,'utf8'))){
 const rootFiber={uid:0},plugins=row.locations.map(()=>({})),entries:any[]=[],runtimes=new Map(),fiberIds=new Map()
 for(const [index,mode] of row.fibers.entries()){
  const parent:any={uid:100+index,parent:{fiber:rootFiber}},current:any={uid:1+index,parent:{fiber:['child','unaffected-parent'].includes(mode)?parent:rootFiber}}
  const entry:any={fiber:{ctx:{fiber:['child','unaffected-parent'].includes(mode)?parent:current}}};current.entry=entry;parent.entry=entry
  if(mode==='stale-wrapper')entry.fiber.ctx.fiber=rootFiber
  if(!['unmanaged','unlisted'].includes(mode))entries.push(entry)
  const fibers=mode==='empty'?[]:mode==='child'?[parent,current]:[current]
  fibers.forEach((fiber:any,offset:number)=>fiberIds.set(fiber,`${index}:${offset}`));runtimes.set(plugins[index],{fibers})
 }
 const importers=new Map<string,Set<string>>()
 for(const [child,parent] of row.graph){const values=importers.get(urls[child]!)??new Set();values.add(urls[parent]!);importers.set(urls[child]!,values)}
 const target:any={ctx:{loader:{entries:()=>entries},registry:{get:(plugin:any)=>runtimes.get(plugin)}},
  moduleGraph:async()=>importers,hostModules:async()=>new Set(row.host.map((index:number)=>urls[index])),
  pluginsOf:(url:string)=>plugins.filter((plugin:any,index:number)=>urls[row.locations[index]]===url)}
 const plan=await (Hmr.prototype as any).planReplacement.call(target,new Set(row.stale.map((index:number)=>urls[index])),[join(directory,'package')+sep])
 result.push({mode:row.mode,pending:plan.pending.map((item:any)=>({node:urls.indexOf(item.url),reason:item.reason})),evicted:[...plan.evicted].map(url=>urls.indexOf(url)),manifests:[...plan.manifests].map((path:any)=>relative(directory,path).replaceAll('\\','/')),plugins:[...plan.plugins].map(plugin=>plugins.indexOf(plugin)),fibers:[...plan.fibers].map(fiber=>fiberIds.get(fiber))})
}
process.stdout.write(JSON.stringify(result))
