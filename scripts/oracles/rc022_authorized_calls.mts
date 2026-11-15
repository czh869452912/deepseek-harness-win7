import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Registry=(await load('packages/typert/registry/src/index.ts')).default,Access=(await load('packages/api/remote-access/src/index.ts')).default,Gateway=(await load('packages/api/gateway/src/index.ts')).default
const {Remote,RemoteScope,TypertRemoteService}=await load('packages/typert/protocol/src/index.ts'),{Peer}=await load('packages/client/connection/src/peer.ts'),{z}=await load('node_modules/zod/index.js')
const cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const c of cases){const ctx=new Context(),counts={lookup:0,context:0,method:0,policy:0};await ctx.plugin(Registry);await ctx.plugin(Access);await ctx.plugin(Gateway)
 class Fixture extends TypertRemoteService{
  static inject=['remoteAccess']
  constructor(child:any){super(child,'fixture')}
  seen(data:any=null){counts.method++;const invocation=this.ctx.invocation;return {principal:invocation.peer.principal,service:invocation.service,wire:invocation.request.args,data}}
  @Remote open(){return this.seen()}
  @Remote lookup(agent:any){return this.seen({id:agent.id})}
  @RemoteScope('agentScope') scoped(){return this.seen()}
  @Remote({resources:{session:(ids:any)=>ids}}) several(ids:any){return this.seen(ids)}
  @Remote read(request:any){return this.seen(request)}
  @Remote annotate(request:any){return this.seen(request)}
  @Remote list(){return this.seen(['a','b'].filter(id=>this.ctx.remoteAccess.allows({kind:'session',id})))}
 }
 try{await ctx.plugin(Fixture);ctx.typert.resources.register('session',{field:'sessionId'})
  ctx.typert.lookups.register('agent',{parameter:'agent',wire:'agentId',hostTypeSymbol:'Agent',wireTypeSymbol:'Id',resource:'session',resolve:(id:any)=>{counts.lookup++;return {id}}})
  ctx.typert.contexts.registerHost('agentScope',{wire:'scopeId',wireTypeSymbol:'Id',resource:'session',identity:()=>undefined,resolve:()=>{counts.context++;return ctx}})
  ctx.remoteAccess.registerPolicy('guest',{bindings(){counts.policy++;return c.held.map((resource:any)=>({resource,role:{actions:['open','lookup','scoped','several','read','list','annotate'].map(name=>'fixture/'+name)}}))}})
  const codec={mode:'strict',typeSymbol:'Request',create:()=>z.object({title:z.string()})},descriptor={id:'fixture#annotate',service:'fixture',namespace:'fixture',method:'annotate',parameters:[{name:'request',wire:'request',source:'json',codec}],result:{mode:'src-json'},invocation:{kind:'direct'}}
  ctx.typert.register({package:'fixture',face:'host',model:{},schemas:[],invocations:[descriptor]})
  const peer=new Peer(ctx,{principal:c.owner?{kind:'owner'}:{kind:'guest',guest:'a'}});if(c.disposed)await peer.dispose()
  let result;try{result={value:await ctx.typertGateway.invoke({namespace:'fixture',method:c.method,args:c.args,peer})}}catch(error:any){result={error:{code:error.code,details:error.details}}}
  rows.push({name:c.name,...result,counts})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
