/** Observe definition/use scope against unchanged fixed Cordis code. */
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const base=process.argv[2]!, module=async(name:string)=>import(pathToFileURL(resolve(base,'vendor/cordis/src/'+name+'.ts')).href)
const {Context}=await module('context'),{Service}=await module('service'),{symbols,getTraceable}=await module('utils'),result:any={}
{
 const ctx=new Context(),disposed:any[]=[],seen:any[]=[];ctx.provide('secret','provider')
 class Api extends Service{
   constructor(owner:any){super(owner,'api')}
   read(){const owner=this.ctx.fiber;this.ctx.effect(()=>()=>{disposed.push(owner)});this.ctx.logger.info('api read');return [this.ctx.secret,owner]}
   get value(){return this.ctx.secret}
   [Service.invoke](){return this.read()}
 }
 const provider=await ctx.inject(['secret'],(owner:any)=>{new Api(owner)})
 const realm=ctx.isolate('secret');realm.provide('secret','caller')
 const consumer=await realm.inject(['api'],(owner:any)=>{
   const proxy=owner.api,first=proxy.read(),second=proxy()
   seen.push(first[0],first[1]===owner.fiber,proxy.value,second[0],second[1]===owner.fiber,proxy.ctx===owner,proxy[symbols.caller]===owner,proxy[symbols.original]===ctx.get('api')[symbols.original])
   Reflect.set(proxy,'ctx',ctx);seen.push(proxy.ctx===owner)
 })
 result.allowed=[seen,ctx.logger.buffer.filter((row:any)=>row.args[0]==='api read').map((row:any)=>row.fiber?.deref()===provider)]
 await consumer.dispose();result.cleanup=disposed.map(owner=>owner===consumer);await ctx.fiber.dispose()
}
{
 const ctx=new Context();await ctx.plugin((owner:any)=>{owner.provide('secret','hidden')})
 class Api extends Service{read(){return this.ctx.secret}}
 await ctx.plugin((owner:any)=>{new Api(owner,'api')})
 const seen:any[]=[]
 await ctx.inject(['secret','api'],(owner:any)=>{try{owner.api.read()}catch(error:any){seen.push(error.message)}seen.push(owner.secret)})
 try{getTraceable(ctx,ctx.get('api')).read()}catch(error:any){seen.push(error.message)}
 result.denied=seen;await ctx.fiber.dispose()
}
{
 const ctx=new Context(),values:any[]=[],seen:any[]=[];ctx.provide('secret',7)
 class Api extends Service{read(){return this.ctx.secret}get value(){return this.read()}}
 await ctx.inject(['secret'],(owner:any)=>{values.push(new Api(owner,'api'))})
 const derived=values[0][Service.extend]({extra:true})
 await ctx.plugin((owner:any)=>{const proxy=getTraceable(owner,derived);seen.push(proxy.read(),proxy.value)})
 result.inherited=seen;await ctx.fiber.dispose()
}
{
 const ctx=new Context(),definition=ctx.extend(),useSite=ctx.extend(),shadow=useSite.extend({[symbols.shadow]:definition})
 const tracked={ctx:definition,[symbols.tracker]:{property:'ctx',noShadow:true},read(){return [this.ctx===useSite,(this as any)[symbols.caller]===definition]}}
 const proxy=getTraceable(shadow,tracked);result.noShadow=proxy.read()
 Reflect.set(proxy,symbols.caller,ctx);result.noShadow.push((proxy as any)[symbols.caller]===definition)
 await ctx.fiber.dispose()
}
{
 const ctx=new Context(),seen:any[]=[],disposed:any[]=[];ctx.provide('secret','provider')
 class Api extends Service{
   scope(){return this.ctx.extend({marker:'derived'})}
   pluginType(){return Api}
   mount(){return this.ctx.extend({marker:'derived'}).inject(['secret'],(child:any)=>{
     seen.push(child.secret,child.marker);child.effect(()=>()=>disposed.push('child'))
   })}
 }
 await ctx.plugin((owner:any)=>{new Api(owner,'api')})
 const realm=ctx.isolate('secret');realm.provide('secret','caller')
 let child:any
 const consumer=await realm.inject(['api'],async(owner:any)=>{
   const scope=owner.api.scope();seen.push(scope.marker,Object.hasOwn(scope,symbols.shadow),owner.api.pluginType()===Api)
   child=await owner.api.mount();seen.push(child.parent.fiber===owner.fiber)
 })
 await consumer.dispose();result.nested=[seen,disposed];await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(result))
