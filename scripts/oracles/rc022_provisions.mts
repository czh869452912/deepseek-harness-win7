/** Actual fixed Source service retention and isolation observations. */
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const { Context }=await import(pathToFileURL(resolve(process.argv[2]!,'vendor/cordis/src/context.ts')).href)
const barrier=()=>Promise.withResolvers<void>(), result:any={}
for(const action of ['dispose','restart'] as const){
  const ctx=new Context(),realm=ctx.isolate('service'),events:string[]=[],disposing=barrier(),release=barrier(),instances:any[]=[]
  const provider=await ctx.plugin((owner:any)=>{
    const value={alive:true};instances.push(value)
    owner.isolate('service',realm[Context.isolate].service).provide('service',value)
    owner.effect(()=>()=>{events.push('provider');value.alive=false})
  })
  const consumer=await realm.inject(['service'],(owner:any)=>async()=>{
    disposing.resolve();await release.promise;events.push(owner.service.alive?'consumer':'broken')
  })
  const task=provider[action]();await disposing.promise
  const waiting=[events.length,instances[0].alive];release.resolve();await task;await consumer.await()
  result[action]=[waiting,[...events],instances[0].alive]
  await ctx.fiber.dispose()
}
{
  const ctx=new Context(),observed:any[]=[];ctx.provide('view','outer')
  const fiber=await ctx.inject(['view'],async(owner:any)=>{
    const isolated=owner.isolate('view'),withdraw=isolated.provide('view','inner')
    observed.push(owner.view,isolated.view)
    await isolated.plugin((child:any)=>{observed.push(child.view)})
    await withdraw();observed.push(owner.view,isolated.view)
  })
  let privateError=''
  await ctx.plugin((owner:any)=>{
    owner.isolate('private').provide('private',true)
    try{void owner.private}catch(error:any){privateError=error.message}
  })
  result.isolation=[observed,Object.keys(fiber.committed),fiber.provisions.size,privateError]
  await ctx.fiber.dispose()
}
{
  const ctx=new Context(),applied:any[]=[],withdraw=ctx.provide('service','first'),first=ctx.reflect._getImpl('service')
  const consumer=await ctx.inject(['service'],(owner:any)=>{applied.push(owner.service)})
  const epoch=(consumer as any)._runner.epoch
  await withdraw();await consumer.await();const pending=consumer.state
  ctx.provide('service','second');const second=ctx.reflect._getImpl('service');await consumer.await()
  result.identities=[first.ctx.fiber===second.ctx.fiber,first.uid!==second.uid,epoch!==(consumer as any)._runner.epoch,pending,applied]
  await ctx.fiber.dispose()
}
{
  const ctx=new Context(),gate=barrier(),started=barrier(),seen:any[]=[],withdraw=ctx.provide('service','old')
  const consumer=await ctx.inject(['service'],(owner:any)=>{
    const value=owner.service;seen.push(value)
    return async()=>{if(value==='old'){started.resolve();await gate.promise;seen.push('retained-'+owner.service)}}
  })
  const task=withdraw();await started.promise;ctx.provide('service','new');gate.resolve();await task;await consumer.await()
  result.retired=seen;await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(result))
