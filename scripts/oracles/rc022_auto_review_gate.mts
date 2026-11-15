import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),AutoReview=await load('packages/experimental/auto-review/src/index.ts'),{HarnessError}=await load('packages/llm/llm/src/index.ts')
const snapshots=JSON.parse(readFileSync(process.argv[4]!,'utf8')),rows:any[]=[]
for(const {name} of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const item=structuredClone(snapshots.find((c:any)=>c.name===(name==='inner'?'ptc-valid':'native')))
 const session:any={id:'review-session',header:item.meta,surface:{nodes:item.nodes},selected:name==='non-auto'?'workspace-write':'auto',snapshotEvents:()=>item.events,requestHeader:()=>item.header??undefined,isOwnSeq:(seq:number)=>seq>=item.own}
 const ctx=new Context(),calls:any[]=[],requests:any[]=[],signals:any[]=[],admission:any[]=[],caller=new AbortController(),callerReason=Error('caller stopped');let available:any
 const streamStarted=Promise.withResolvers<void>(),nextStarted=Promise.withResolvers<void>()
 if(name==='caller-aborted')caller.abort(callerReason)
 const permission:any={current:(s:any)=>s.selected,registerAuto:(admit:any)=>ctx.effect(()=>{if(available)throw Error('duplicate');available=admit;return ()=>{available=undefined}}),set:(s:any,value:string)=>{calls.push('select:'+value);try{available()}catch(error:any){admission.push(error.message)}s.selected=value}}
 const services:any={permissionPresets:permission,approval:{overrideOf:()=>name==='deny-never'?'never':'ask'},sessions:{list:()=>[session]},tools:{},workingDirectory:{ensure:async()=>{calls.push('directory');return 'C:/gate'}},llm:{async *stream(options:any){
  calls.push('stream');signals.push(options.signal);const {signal,...request}=options;requests.push(request);streamStarted.resolve()
  if(['unload-during-review','root-shutdown'].includes(name)){await new Promise<void>(resolve=>signal.addEventListener('abort',()=>resolve(),{once:true}));throw signal.reason}
  if(name==='caller-aborted')throw signal.reason
  if(name==='provider-error')throw Error('provider secret')
  if(name==='provider-typed-error')throw new HarnessError('typed provider secret','PROVIDER')
  if(name==='provider-nonerror')throw 'middleware refused'
  const decision=name.startsWith('deny')?'deny':'allow',value:any={risk:decision==='deny'?'medium':'low',decision}
  if(name==='deny-empty')value.reason='';else if(decision==='deny')value.reason='raw reason 🐱'
  const text=JSON.stringify(name==='invalid-json-protocol'?{risk:'high',decision:'allow'}:value)
  yield {type:'block-start',index:0,blockType:'text'};yield {type:'block-end',index:0,block:{type:'text',text}};yield {type:'finish',reason:{kind:'stop'}}
 }}}
 for(const [key,value] of Object.entries(services)){ctx.provide(key);ctx[key]=value}
 let owner=await ctx.plugin(AutoReview)
 const execution:any={...item.execution,agent:name==='no-agent'?undefined:{session},signal:caller.signal}
 if(name==='outer-code')execution.name='run_code'
 if(name==='missing-facts')item.header=null
 const next=async()=>{calls.push('next');nextStarted.resolve();if(name==='unload-during-next')await new Promise<void>(resolve=>signals.at(-1).addEventListener('abort',()=>resolve(),{once:true}));const kind=['deny-downstream','allow-downstream-deny'].includes(name)?'deny':name==='deny-downstream-ask'?'ask':name==='allow-downstream-cancel'?'cancel':'allow';return ['deny','ask'].includes(kind)?{kind,reason:'downstream'}:{kind}}
 try{
  const task=ctx.waterfall('tools/pre-execute',execution,next)
  if(['unload-during-review','root-shutdown'].includes(name)){await streamStarted.promise;await (name==='root-shutdown'?ctx.fiber.dispose():owner.dispose())}
  else if(name==='unload-during-next'){await nextStarted.promise;await owner.dispose()}
  const result=await task,second=name==='repeat'?await ctx.waterfall('tools/pre-execute',execution,next):null
  const before={selected:session.selected,available:available!==undefined,signals:signals.map(s=>s.aborted)}
  await owner.dispose()
  if(name==='reinstall'){owner=await ctx.plugin(AutoReview);calls.push('reinstalled')}
  const after={selected:session.selected,available:available!==undefined,signals:signals.map(s=>s.aborted),callerIdentity:name==='caller-aborted'?signals.every(s=>s.reason===callerReason):null}
  rows.push({name,result,second,before,after,calls,admission,requests})
 }finally{await ctx.fiber.dispose()}
}
const {ToolExecutionPipeline}=await load('packages/core/tools/src/pipeline.ts')
for(const name of ['allowed-once','rejected','cancelled','unavailable','missing-service','agentless','empty-reason','invalid']){
 const requests:any[]=[],approval={request:async(value:any)=>{const {agent,signal,...request}=value;requests.push(request);return name==='empty-reason'?'unavailable':name}},ctx={get:()=>['missing-service','empty-reason'].includes(name)?undefined:approval}
 const execution={name:'probe',callId:'call',agent:name==='agentless'?undefined:{},signal:new AbortController().signal},ask={kind:'ask',reason:name==='empty-reason'?'':'audit',displayReason:{en:'Prompt',zh:'提示'}}
 let result
 try{result=await (ToolExecutionPipeline.prototype as any).serviceAsk.call({ctx},execution,ask)}catch(error:any){result={error:error.message}}
 rows.push({name:'ask-'+name,result,requests})
}
{
 const ctx=new Context(),{default:Sessions}=await load('packages/core/session/src/index.ts'),{default:Projections}=await load('packages/session/session-projection/src/index.ts'),{default:Approval}=await load('packages/interaction/user-approval/src/index.ts')
 await ctx.plugin(Sessions);await ctx.plugin(Projections);const owner=await ctx.plugin(Approval,{policy:'ask'})
 const session=ctx.sessions.create('provider'),injected:any[]=[],answered:any[]=[],agent={session,inject:(message:any)=>{const {id,...item}=message;injected.push(item)}},service:any=ctx.approval
 const request={agent,toolName:'probe',callId:'call',reason:'audit',displayReason:{en:'Prompt',zh:'提示'},signal:new AbortController().signal}
 ctx.on('approval/request',(value:any)=>{answered.push({reason:value.reason,displayReason:value.displayReason});return 'allowed-once'})
 try{
  const initial=service.approvalProjectionHandle.stateOf(session);let idleError
  try{await service.request(request)}catch(error:any){idleError=error.message}
  session.append('turn/start',{turn:1});const allowed=await service.request(request)
  service.setPolicy(agent,'never');service.setPolicy(agent,'never');const rejected=await service.request(request)
  session.append('turn/end',{turn:1,reason:{kind:'completed'}});const final=service.approvalProjectionHandle.stateOf(session)
  const events=session.snapshotEvents().filter((event:any)=>event.type.startsWith('approval/')).map((event:any)=>{const {id,...data}=event.data;return {type:event.type,data}})
  await owner.dispose();rows.push({name:'approval-provider',initial,final,allowed,rejected,idleError,events,injected,answered,withdrawn:ctx.get('approval')===undefined})
 }finally{await ctx.fiber.dispose()}
}
console.log(JSON.stringify(rows))
