import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,load=(name:string)=>import(pathToFileURL(resolve(root,'vendor/cordis/src/'+name+'.ts')).href)
const {Context}=await load('context'),{Logger}=await load('logger'),ctx=new Context(),result:any={}
const rows:any[]=[],disposers:any[]=[]
for(const threshold of [null,0,1,2,3]){
 const received:any[]=[];rows.push(received)
 disposers.push(ctx.logger.exporter({levels:threshold===null?{}:{default:threshold,named:null},export(msg:any){received.push([msg.type,msg.level,msg.sn])}}))
}
const log=ctx.logger('named')
for(const name of ['error','warn','info','debug'])log[name]('hello')
result.levels=rows.map(received=>received.map((row:any)=>row.slice()));disposers[0]();result.disposer=[ctx.logger.exporters.has(2),ctx.logger.exporters.has(6)]
const before:any[]=[],after:any[]=[]
ctx.logger.exporter({export(msg:any){before.push(msg);msg.name='changed';msg.args.push('shared')}})
ctx.logger.exporter({export(msg:any){after.push(msg)}})
log.info(null);result.records=[before.at(-1)!==after.at(-1),after.at(-1).name,after.at(-1).args,ctx.logger.buffer.at(-1).name]
log.info(new AggregateError([]));result.empty_aggregate=after.length
new Logger({name:'meta',meta:{name:'override',level:9,sn:123,args:['ignored']}},ctx.logger).info('actual')
result.meta=[after.at(-1).name,after.at(-1).level,after.at(-1).sn,after.at(-1).args]
ctx.logger.bufferSize=2;const reference=ctx.logger.buffer,child=ctx.extend()
for(let value=0;value<4;value++)child.logger('ring').info(value)
result.buffer=[reference===ctx.logger.buffer,reference.length,reference.map((msg:any)=>msg.args[0])]
result.empty_name=ctx.intercept('logger',{name:'inherited'}).logger('').name
await ctx.fiber.dispose();result.disposed=ctx.logger.exporters.size
process.stdout.write(JSON.stringify(result))
