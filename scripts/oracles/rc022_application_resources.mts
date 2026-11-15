import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const {Context,Service}=await load('vendor/cordis/src/index.ts'),Registry=(await load('packages/typert/registry/src/index.ts')).default,Access=(await load('packages/api/remote-access/src/index.ts')).default,Gateway=(await load('packages/api/gateway/src/index.ts')).default,{Peer}=await load('packages/client/connection/src/peer.ts'),{remoteMethods}=await load('packages/typert/protocol/src/index.ts'),Controller=(await load('packages/api/session-controller/src/index.ts')).default,{ApiSessionAgentController}=await load('packages/api/session-controller/src/agent.ts'),Presets=(await load('packages/preset/agent-preset-registry/src/index.ts')).default,Subagents=(await load('packages/subagent/subagent/src/index.ts')).default,Loader=(await load('vendor/loader/src/index.ts')).default
const input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],capture=new Context(),sentinel=Error('stop after resource registration'),initialize=ApiSessionAgentController.prototype.initialize
await capture.plugin(Registry)
try{
 ApiSessionAgentController.prototype.initialize=()=>{throw sentinel}
 const controller=new Controller(capture,{})
 try{await controller[Service.init]()}catch(error){if(error!==sentinel)throw error}
 const resolver=capture.typert.resources.get('session').resolve
 for(const [index,test]of input.cases.entries()){let answer;try{const value=resolver(test);answer={value:value??null,absent:value===undefined}}catch(error:any){answer={error:error.message.includes('must not contain both')?'coexisting':'invalid-address'}}rows.push({name:'reader:'+index,...answer})}
}finally{ApiSessionAgentController.prototype.initialize=initialize;await capture.fiber.dispose()}
const fixture=await setup(join(input.workspace,'source')),{ctx}=fixture
try{
 await ctx.plugin(Registry);await ctx.plugin(Access);await ctx.plugin(Gateway);await ctx.plugin(Loader);await ctx.plugin(Presets,{default:'coding'});await ctx.agentPresets.register({id:'coding',plugins:[]})
 for(const [cls,names]of [[ctx.agentPresets,['select']],[ctx.subagents,['prompt','interruptByUser']]]as any){for(const marker of remoteMethods(cls)){if(names.includes(marker.method)){const readers=marker.resources;rows.push({name:'marker:'+marker.method,invocation:marker.invocation,resource:readers?readers.session(marker.method==='prompt'?{childSessionId:'child'}:'child'):null})}}}
 const parent=(await ctx.agents.create({sessionId:'parent',agentOptions:{provider:'script',model:'model'},setup:async(child:any)=>{await ctx.agentPresets.mount(child,'coding')}})).agent
 await fixture.service.startActivation({provider:'spawn',parent,childId:'child',name:'worker',label:'Task',prompt:[{type:'text',text:'Task'}],signal:fixture.signal,delivery:'caller'})
 while(ctx.agents.get('child').status!=='running')await new Promise(resolve=>setTimeout(resolve,0))
 let held:string[]=[];const lookups:string[]=[],received:any[]=[]
 ctx.remoteAccess.registerPolicy('guest',{bindings:()=>held.map(id=>({resource:{kind:'session',id},role:{actions:['subagents/prompt','subagents/interruptByUser','agentPresets/select']}}))})
 ctx.typert.lookups.configure('agent',(id:string)=>{lookups.push(id);return ctx.agents.get(id)})
 ctx.on('agent/inbox/inserted',({message}:any)=>{if(message.source.rpcId)received.push(message.source)})
 const peer=new Peer(ctx,{principal:{kind:'guest',id:'g'}})
 async function invoke(name:string,namespace:string,method:string,args:any,grants:string[]){held=grants;const before=[lookups.length,received.length,parent.session.seq];let result;try{const value=await ctx.typertGateway.invoke({namespace,method,args,peer,signal:fixture.signal});result={value:method==='prompt'?{accepted:!!value.messageId}:value}}catch(error:any){result={error:{code:error.code,details:error.details}}}rows.push({name,...result,lookupCount:lookups.length-before[0]!,messages:received.length-before[1]!,parentChanged:parent.session.seq!==before[2]})}
 const request={requestId:'rpc',childSessionId:'child',sessionId:'parent',delivery:'queue',content:[{type:'text',text:'authorized'}]}
 await invoke('wrong-parent-grant','subagents','prompt',{request},['parent']);await invoke('target-grant','subagents','prompt',{request},['child']);rows.push({name:'attribution',source:received.at(-1)})
 await invoke('preset-denied','agentPresets','select',{agentId:'parent',agentPreset:'coding'},['child']);await invoke('preset-allowed','agentPresets','select',{agentId:'parent',agentPreset:'coding'},['parent']);await invoke('interrupt-denied','subagents','interruptByUser',{childSessionId:'child'},['parent']);await invoke('interrupt-allowed','subagents','interruptByUser',{childSessionId:'child'},['child']);await peer.dispose()
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
