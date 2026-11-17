import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {setup,load} from './rc022_subagent_fixture.mts'
import {definitions} from './rc022_schedule_definition.mts'
const input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),{ctx}=await setup(join(input.workspace,'source'))
const {createScope}=await load('packages/core/scope/src/index.ts'),tool=await load('packages/schedule/tool-schedule/src/index.ts'),{ScheduleInputError}=await load('packages/schedule/schedule/src/index.ts'),{executeToolFixture}=await load('packages/test-support/tool-testkit/src/index.ts')
let mode='';const requests:any[]=[],sections:any[]=[],rows:any[]=[]
async function invoke(name:string,...args:any[]){
 if(mode==='internal')throw Error('private backend path')
 if(['invalid_rule','invalid_selector'].includes(mode))throw new ScheduleInputError(mode,'declared error')
 requests.push([name,...(['create','edit'].includes(name)?args.slice(0,2):args)])
 if(name==='list')return {items:[input.tasks.at],shown:1,total:1,limit:100,offset:0}
 if(name==='view'&&args[0].id==='missing')return {id:'missing',code:'schedule_not_found'}
 if(name==='edit'&&args[0].action==='delete')return {id:args[0].id,deleted:true}
 return input.tasks[name==='view'?args[0].id:'at']
}
ctx.provide('schedule');ctx.schedule={deliveryLimits:()=>({newSessionIntervalSeconds:90}),...Object.fromEntries(['create','list','view','edit'].map(name=>[name,(...args:any[])=>invoke(name,...args)]))}
ctx.provide('agentPresets');ctx.agentPresets={composedPreset:()=> 'selected-preset'}
const lease=await ctx.agents.create({sessionId:'root',agentOptions:{provider:'script',model:'model'}}),agent=lease.agent,scope=createScope(ctx,agent),original=ctx.systemPrompt.section.bind(ctx.systemPrompt)
ctx.systemPrompt.section=(spec:any)=>{sections.push(spec);return original(spec)}
try{
 const fiber=await scope.ctx.plugin(tool),descriptors=[]
 for(const seconds of [60,90,120,7200])descriptors.push(await definitions(seconds))
 rows.push({name:'descriptors',value:descriptors})
 rows.push({name:'scope',outside:ctx.tools.get('schedule_create')!==undefined,inside:ctx.tools.get('schedule_create',agent)!==undefined,guidance:sections.at(-1).text({scope:agent}),outsideGuidance:sections.at(-1).text({scope:undefined})})
 const globalFiber=await ctx.plugin(tool)
 for(const [index,row] of input.cases.entries()){
  mode=row.mode??'';agent.options.subagentDepth=mode==='delegated'?1:0
  const before=requests.length,result=await executeToolFixture(ctx,{callId:'call-'+index,name:row.tool,arguments:row.args,agent:mode==='no-agent'?undefined:agent,signal:new AbortController().signal})
  rows.push({name:row.name,value:{isError:result.isError,value:result.value??null,content:result.content},requests:requests.slice(before),presentation:ctx.tools.get(row.tool,agent).presentCall(row.args)})
 }
 await globalFiber.dispose();await fiber.dispose();rows.push({name:'disposed',inside:ctx.tools.get('schedule_create',agent)!==undefined})
 console.log(JSON.stringify(rows))
}finally{await scope.dispose();await lease.dispose();await ctx.fiber.dispose()}
