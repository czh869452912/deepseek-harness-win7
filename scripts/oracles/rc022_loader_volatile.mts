/** Public Loader journeys against unchanged fixed upstream. */
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const root=process.argv[2]!
const load=async(path:string)=>import(pathToFileURL(resolve(root,path)).href)
const {Context}=await load('vendor/cordis/src/context.ts')
const {default:Loader}=await load('vendor/loader/src/index.ts')
const {default:z}=await load('vendor/schemastery/src/index.ts')
const result:any={}
for(const mode of ['ordinary','retained','throwing','whole']){
  const ctx=new Context();await ctx.plugin(Loader)
  const applied:any[]=[],disposed:any[]=[],events:any[]=[],hooks:any[]=[]
  let Config=z.object({fixed:z.string().default('fixed'),title:z.string().default('hello').volatile(),count:z.number().min(0).default(1).volatile()})
  if(mode==='whole')Config=z.object({title:z.string()}).volatile()
  const plugin={Config,apply(owner:any,config:any){
    applied.push(config);owner.effect(()=>()=>{disposed.push(disposed.length)})
    owner.on('loader/volatile-update',(paths:any)=>{
      events.push([paths,mode==='whole'?config.get():[config.title.get(),config.count.get()]])
      if(mode==='throwing')throw new Error('listener rejected')
    })
    if(mode==='retained')owner.on('internal/update',(candidate:any)=>{hooks.push(candidate.title.get())})
  }}
  ctx.loader.builtins.probe=plugin
  const id=await ctx.loader.create({id:'first',name:'cordis:probe',config:{title:'hello'}})
  const entry=ctx.loader.resolve(id),fiber=entry.fiber;await fiber.await()
  await ctx.loader.create({id:'second',name:'cordis:probe',config:{title:'hello'}})
  await ctx.loader.await()
  const initial=fiber.effectiveConfig,reference=mode==='whole'?initial:initial.title
  await entry.update({config:{title:'next',...(mode==='whole'?{}:{count:2})}})
  result[mode+'-commit']=[applied.length,fiber.effectiveConfig===initial,(mode==='whole'?initial:initial.title)===reference,[...events],[...hooks],[...disposed]]
  if(mode!=='whole'){
    await entry.update({config:{title:'rejected',count:-1}})
    result[mode+'-invalid']=[fiber.rawConfig,reference.get(),applied.length,events.length]
    await entry.update({config:{fixed:'other',title:'mixed'}});await fiber.await()
    result[mode+'-mixed']=[applied.length,fiber.effectiveConfig===initial,reference.get(),fiber.effectiveConfig.title.get(),[...hooks],events.length,disposed.length]
  }
  await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(result))
