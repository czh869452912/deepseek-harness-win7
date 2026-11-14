/** Associated members on unchanged fixed Cordis Source. */
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,load=(name:string)=>import(pathToFileURL(resolve(root,'vendor/cordis/src/'+name+'.ts')).href)
const {Context}=await load('context'),{Service}=await load('service'),{symbols}=await load('utils'),result:any={}
for(const generic of [false,true]){
 const ctx=new Context()
 class Api extends Service{label='own';constructor(owner:any){super(owner,'api')}read(){return this.ctx.api.secret}}
 class Tracked{label='own';[symbols.tracker]={associate:'api',property:'ctx'};constructor(public ctx:any){}read(){return this.ctx.api.secret}}
 await ctx.plugin((owner:any)=>{owner.provide('api.secret','provider')})
 const instances:any[]=[]
 await ctx.inject(['api.secret'],(owner:any)=>{const api=generic?new Tracked(owner):new Api(owner);if(generic)owner.provide('api',api);instances.push(api)})
 const access:any[]=[]
 const extension=await ctx.plugin((owner:any)=>{
  owner.accessor('api.label',{
   get(this:any,receiver:any,error:any){access.push([this.fiber===consumer,receiver[symbols.original]===instances[0]]);return 'extension'},
   set(this:any,value:any,receiver:any,error:any){access.push([this.fiber===consumer,receiver[symbols.original]===instances[0],value]);return true}
  })
 })
 const realm=ctx.isolate('api.secret');realm.provide('api.secret','caller')
 const consumer=await realm.inject(['api','api.secret'],()=>{}),proxy=consumer.ctx.api
 result[String(generic)]=[proxy.secret,proxy.read(),proxy.label]
 proxy.label='written';result[String(generic)].push(access,instances[0].label)
 await extension.dispose();result[String(generic)].push(proxy.label)
 const denied:any[]=[]
 await ctx.inject(['api'],(owner:any)=>{try{owner.api.secret}catch(error:any){denied.push(error.message)}})
 result[String(generic)].push(denied)
 const {getTraceable}=await load('utils'),metadata=consumer.ctx.extend({tag:'caller-metadata'})
 result[String(generic)].push(getTraceable(metadata,{ctx,[symbols.tracker]:{property:'ctx'},read(){return this.ctx.tag}}).read())
 await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(result))
