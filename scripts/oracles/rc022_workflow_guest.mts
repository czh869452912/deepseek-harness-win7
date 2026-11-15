import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {PtcWorkflowRun}=await load('packages/workflow/workflow-ptc/src/host.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const testcase of cases){
 const events:any[]=[],requests:any[]=[],closed:number[]=[];let active=0,maxActive=0
 const ctx={workingDirectory:{async ensure(){return 'C:/fixed-work'}},logger:{warn(){}}}
 const subagents={async startActivation(spec:any){
  const index=requests.length+1;requests.push({cwd:spec.cwd,label:spec.label,delivery:spec.delivery,prompt:spec.prompt,options:spec.agentOptions??null,schema:spec.outputSchema??null});active++;maxActive=Math.max(maxActive,active)
  return {childId:'child-'+index,result:new Promise(resolve=>setTimeout(()=>resolve({output:[{type:'text',text:'reply:'+spec.prompt[0].text}],stopReason:testcase.childStop??'completed',structured:{ok:true}}),index===2?150:5)),async dispose(){closed.push(index);active--}}
 }}
 const event=(type:string)=>(value:any)=>events.push({type,value}),observer={phase:event('phase'),log:event('log'),agentStart:event('start'),agentEnd:event('end')}
 const init={meta:{name:testcase.name,description:'current Guest'},body:testcase.body,limits:{maxConcurrentAgents:testcase.concurrent??2,maxTotalAgents:testcase.total??20,maxItemsPerCall:testcase.items??100,syncTimeoutMs:testcase.timeout??1000},...testcase.args===undefined?{}:{args:testcase.args}}
 const runtime={sandboxMode:'read-only',programFormat:'function-body',resolve:(spec:any)=>spec,run:async(spec:any)=>({logs:[],value:await new Function('workflowHost',`return (async () => {${spec.program}})()`)(spec.bindings[0].functions)})}
 const run=new PtcWorkflowRun(ctx,subagents,runtime,'run',init.meta,{},init,'stub',{mode:'read-only'},observer),result=await run.result;await run.dispose()
 if(result.error){result.error=result.error.split('\n')[0];if(['sync-timeout','syntax'].includes(testcase.name))result.error=testcase.name}
 rows.push({name:testcase.name,result,events,requests,closed:closed.sort((a,b)=>a-b),maxActive,workers:0})
}
process.stdout.write(JSON.stringify(rows))
