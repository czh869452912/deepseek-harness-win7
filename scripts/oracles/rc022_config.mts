/** Config journeys against unchanged fixed Source; no copied implementation. */
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const { Context } = await import(pathToFileURL(resolve(process.argv[2]!, 'vendor/cordis/src/context.ts')).href)
const deferred = () => { let resolve!: () => void, reject!: (error: Error) => void; const promise = new Promise<void>((a,b) => { resolve=a; reject=b }); return {promise,resolve,reject} }
const result: any = {}
{
  const ctx = new Context(), applied: any[] = [], raw = {value:0}
  const fiber = await ctx.plugin((owner: any, config: any) => { applied.push(config) },raw)
  ctx.on('internal/config',(target: any,next: any) => ({...next(),resolved:true}))
  const candidate={value:1}, evaluated=fiber.resolveConfig(candidate)
  result.candidate=[evaluated,fiber.rawConfig===raw,fiber.config===raw,fiber.effectiveConfig===applied[0],applied.length]
  await fiber.update(candidate)
  result.applied=[fiber.rawConfig===candidate,fiber.effectiveConfig===applied.at(-1),fiber.effectiveConfig!==evaluated,applied]
  await ctx.fiber.dispose()
}
{
  const ctx=new Context(), old=deferred(), failed=deferred(), commits:any[]=[], applied:any[]=[]
  ctx.on('internal/commit',(_fiber:any,raw:any)=>{commits.push(raw)})
  const fiber=await ctx.plugin((owner:any,config:any)=>{applied.push(config);owner.on('internal/update',(candidate:any)=>candidate===1?old.promise:candidate===3?failed.promise:undefined)},0)
  const first=fiber.update(1), initial=fiber.effectiveConfig
  const sync=fiber.update(2)===undefined
  old.resolve();await first
  const after=fiber.effectiveConfig, third=fiber.update(3);failed.reject(new Error('update rejected'))
  let error='';try{await third}catch(reason:any){error=reason.message}
  result.retained=[initial,sync,after,error,fiber.rawConfig,fiber.effectiveConfig,commits,applied]
  await ctx.fiber.dispose()
}
for(const action of ['raw retention','restart','dispose']){
  const ctx=new Context(),gate=deferred(),applied:any[]=[]
  const fiber=await ctx.plugin((owner:any,config:any)=>{applied.push(config);owner.on('internal/update',()=>gate.promise)},{value:0})
  const old=fiber.update({value:1})
  if(action==='raw retention')fiber.rawConfig={value:2}
  else if(action==='restart')await fiber.restart()
  else await fiber.dispose()
  gate.resolve();await old
  result[action]=[fiber.effectiveConfig===applied.at(-1),fiber.effectiveConfig,applied]
  await ctx.fiber.dispose()
}
for(const injected of [false,true]){
  const ctx=new Context(),started=deferred(),release=deferred(),applied:any[]=[],disposed:any[]=[]
  ctx.provide('dependency',1)
  const plugin=async(owner:any,config:any)=>{applied.push(config);if(config===1){started.resolve();await release.promise}owner.effect(()=>()=>{disposed.push(config)})}
  Object.assign(plugin,{inject:injected?['dependency']:[]})
  const fiber=await ctx.plugin(plugin,0)
  const first=fiber.update(1);await started.promise
  const second=fiber.update(2),third=fiber.update(3);release.resolve();await Promise.all([first,second,third])
  result['loading-'+injected]=[applied,[...disposed],fiber.state,fiber.effectiveConfig]
  await ctx.fiber.dispose();result['disposed-'+injected]=disposed
}
{
  const ctx=new Context(),seen:any[]=[]
  const fiber=await ctx.plugin((owner:any)=>{owner.on('internal/update',(candidate:any)=>{seen.push(['update',owner.fiber.rawConfig,candidate])})},0)
  ctx.on('internal/commit',(target:any,raw:any)=>{seen.push(['commit',target.rawConfig,raw])})
  fiber.update(1);fiber.update(2,true);result.commit=seen
  await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(result))
