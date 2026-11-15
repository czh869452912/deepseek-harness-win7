import {getEventListeners} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Registry=(await load('packages/typert/registry/src/index.ts')).default,Access=(await load('packages/api/remote-access/src/index.ts')).default,Gateway=(await load('packages/api/gateway/src/index.ts')).default
const {Remote,TypertRemoteService}=await load('packages/typert/protocol/src/index.ts'),{Peer}=await load('packages/client/connection/src/peer.ts'),{z}=await load('node_modules/zod/index.js')
const rows:any[]=[],cases=['duplex','strict-good','strict-bad','peer-cancel','carrier-cancel','early-close','once','unread','invalid-result','wrong-unary','wrong-stream','undefined-uplink','empty-uplink']
class Input{
 returned=false;waiters:any[]=[]
 constructor(readonly values:any[],readonly hold:boolean){}
 [Symbol.asyncIterator](){return this}
 next():Promise<any>{if(this.returned)return Promise.resolve({done:true});if(this.values.length)return Promise.resolve({value:this.values.shift(),done:false});if(!this.hold)return Promise.resolve({done:true});return new Promise(resolve=>this.waiters.push(resolve))}
 return(){this.returned=true;for(const resolve of this.waiters)resolve({done:true});this.waiters=[];return Promise.resolve({done:true})}
}
for(const name of cases){const ctx=new Context();await ctx.plugin(Registry);await ctx.plugin(Access);await ctx.plugin(Gateway);const carrier=new AbortController(),peer=new Peer(ctx,{principal:{kind:'owner'}}),closed:any[]=[]
 class Fixture extends TypertRemoteService{
  constructor(child:any){super(child,'fixture')}
  @Remote({mode:'stream'}) async *duplex(signal:any){try{for await(const value of this.ctx.invocation.uplink())yield {echo:value===undefined?'undefined':value,signal:signal===this.ctx.invocation.signal}}finally{closed.push(true)}}
  @Remote async once(signal:any){const values=[];for await(const value of this.ctx.invocation.uplink())values.push(value);try{this.ctx.invocation.uplink()}catch(error:any){return {values,error:error.message,sameSignal:signal===carrier.signal,window:this.ctx.invocation.uplinkWindow}}}
  @Remote unread(){return 'unread'}
  @Remote({mode:'stream'}) invalid(){return {}}
 }
 try{await ctx.plugin(Fixture)
  if(name.startsWith('strict')){const descriptor={id:'fixture#duplex',service:'fixture',namespace:'fixture',method:'duplex',mode:'stream',parameters:[],cancellation:{parameter:'signal'},invocation:{kind:'direct'},result:{mode:'src-json'},uplink:{codec:{mode:'strict',typeSymbol:'Number',create:()=>z.number()}}};ctx.typert.register({package:'fixture',face:'host',model:{},schemas:[],invocations:[descriptor]})}
  const method=['once','wrong-stream'].includes(name)?'once':name==='unread'?'unread':name==='invalid-result'?'invalid':'duplex',values=name==='strict-good'?[7]:name==='strict-bad'?['bad']:name==='undefined-uplink'?[undefined]:['a',{n:1}],source=new Input(values,['peer-cancel','carrier-cancel','early-close'].includes(name)),request:any={namespace:'fixture',method,args:{},peer,signal:carrier.signal,uplinkWindow:3};if(name!=='empty-uplink')request.uplink=source
  const result:any={};let stream:any
  try{if(['once','unread','wrong-unary'].includes(name))result.value=await ctx.typertGateway.invoke(request)
   else{stream=await ctx.typertGateway.stream(request);const output=[]
    if(['peer-cancel','carrier-cancel','early-close'].includes(name)){output.push((await stream.next()).value);if(name==='peer-cancel')await peer.dispose();else if(name==='carrier-cancel')carrier.abort(Error('cancel'));else await stream.return()}
    if(name!=='early-close')try{for await(const value of stream)output.push(value)}catch(error:any){result.error={code:error.code,details:error.details}}
    result.output=output
   }
  }catch(error:any){result.error={code:error.code,details:error.details}}finally{if(stream)await stream.return()}
  for(let index=0;index<4;index++)await Promise.resolve()
  rows.push({name,result,returned:name==='empty-uplink'?null:source.returned,closed:closed.length,listeners:getEventListeners(carrier.signal,'abort').length+getEventListeners(peer.signal,'abort').length})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
