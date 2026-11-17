import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Runner=(await load('packages/extensions/cordis-host-runner/src/index.ts')).default
const inputs=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const value of inputs.configs){
 const config=Object.fromEntries(Object.entries(value).map(([key,value])=>[key,value==='NaN'?NaN:value==='Infinity'?Infinity:value]))
 try{rows.push({stage:'config',value:Runner.Config(config)})}catch(error:any){rows.push({stage:'config',error:error.message})}
}
for(const mode of inputs.modes){
 const ctx=new Context(),events:any[]=[],messages:any[]=[],injected:any[]=[],results:any[]=[]
 const message=(value:any)=>({content:value.content,source:value.source})
 const agent:any={id:'agent',ctx,steer:(value:any)=>{messages.push(message(value))},inject:(value:any)=>{injected.push(message(value))}}
 try{
  for(const path of ['packages/core/system-prompt/src/index.ts','packages/core/tools/src/index.ts','packages/core/tool-executor-native/src/index.ts']){const module=await load(path);await ctx.plugin(module.default??module)}
  ctx.provide('agents',new Map([[agent.id,agent]]));await ctx.plugin(Runner,{clientInspectTimeoutMs:37})
  const runner=ctx.dynamicCordisRunner
  for(const name of ['cordis/request-run','cordis/request-run-resolved','cordis/dynamic-package','cordis/dynamic-retract'])ctx.on(name,(value:any)=>{events.push([name,structuredClone(value)])})
  const request:any={sessionId:agent.id,plugin:{kind:'new',idPrefix:'probe'},name:'First',purpose:'fixture',code:{client:'return () => {}'}}
  if(mode==='handler')request.code.host='return (ctx) => { const fail = (message) => () => { const error = new Error(message); error.stack = "fixture stack"; throw error }; harness.handle("fail", fail("handler failed")); harness.handle("a\\x00b", fail("c")); harness.handle("a", fail("b\\x00c")) }'
  const definition=runner.define(request),pid=definition.pluginId,packageId=definition.packageId;results.push(definition)
  results.push(await runner.run(agent,pid,packageId,'run'));let rid=events.at(-1)[1].requestId
  if(mode==='rejected'||mode==='failure-unapproved'){
   const resolution=mode==='rejected'?{ok:false,reason:'rejected'}:{ok:false,reason:'client-half-failed',message:'client failed',stack:'fixture stack'}
   results.push(await runner.resolveRequestRun(rid,resolution))
  }else{
   const started=await runner.runHostHalf(agent,pid,packageId,'run',rid,true);results.push(started)
   results.push(await runner.resolveRequestRun(rid,{ok:true,pluginRunId:started.pluginRunId}))
   if(mode==='failure'){
    const updated=runner.define({...request,plugin:{kind:'existing',pluginId:pid},name:'Second'});results.push(updated)
    results.push(await runner.run(agent,pid,updated.packageId,'update'));rid=events.at(-1)[1].requestId
    results.push(await runner.resolveRequestRun(rid,{ok:false,reason:'client-half-failed',message:'client failed',stack:'fixture stack'}))
   }else if(mode==='guard'){
    for(let i=0;i<2;i++)results.push(await runner.reportClientGuardFailure(agent,pid,started.pluginRunId,{message:'guard failed',stack:'fixture stack'}))
   }else if(mode==='render'){
    for(let i=0;i<2;i++)results.push(await runner.reportRenderFailure(agent,pid,started.pluginRunId,{message:'render failed '+i,stack:'fixture stack',slot:'main',abdicated:Boolean(i)}))
   }else if(mode==='handler'){
    for(const method of ['fail','fail','a\0b','a'])results.push(await runner.invoke(pid,started.pluginRunId,method,{}))
   }else if(mode==='panel'){
    results.push(await runner.stopFromPanel(agent,pid));results.push(await runner.undefineFromPanel(agent,pid))
   }else if(mode==='foreign-agent'){
    results.push(await runner.stopFromPanel({id:'foreign'},pid));runner.injectUserContext({id:'agent',inject:()=>{injected.push('wrong')}},'do not inject')
   }
  }
  rows.push({stage:mode,results,events,messages,injected,inventory:runner.inventory(),timeout:runner.inspectRegistry.clientQueryTimeoutMs})
 }finally{await ctx.fiber.dispose()}
}
console.log(JSON.stringify(rows,(_key,value)=>typeof value==='number'&&!Number.isFinite(value)?{number:String(value)}:value))
