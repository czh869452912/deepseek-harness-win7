import fs from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Product,Config}=await load('packages/host/product-telemetry-otel/src/index.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs){
 const ctx=new Context(),options:any[]=[],records:any[]=[],warnings:string[]=[],shutdown:any[]=[]
 let stage='schema',error:any=null
 ctx.logger.warn=(message:string)=>{if(String(message).startsWith('Product telemetry'))warnings.push(String(message))}
 ctx.provide('otel',{createEventReporter(selected:any){
  const {onFailure,...plain}=selected;options.push(structuredClone(plain))
  return {emit(record:any){records.push(structuredClone(record))},async shutdown(signal:AbortSignal){
   if(entry.action==='deadline')await new Promise<void>(resolve=>signal.addEventListener('abort',()=>resolve(),{once:true}))
   shutdown.push({aborted:signal.aborted,reason:signal.aborted?(signal.reason as Error).message:null})
  }}
 }})
 const config={serviceName:'fixture',serviceVersion:'1',...entry.config};if(entry.omit)delete config[entry.omit]
 try{
  const parsed=Config(config);stage='construct'
  const fiber=await ctx.plugin(Product,parsed)
  ctx.productTelemetry.emit({eventName:'fixture',body:'synthetic',timestamp:1700000000000,attributes:{platform:'win32'}})
  await fiber.dispose();stage='done'
 }catch(failure:any){if(stage==='construct')error=failure.message}
 finally{await ctx.fiber.dispose()}
 rows.push({stage,error,options,records,warnings,shutdown,after:ctx.get('productTelemetry',false)!==undefined})
}
process.stdout.write(JSON.stringify(rows))
