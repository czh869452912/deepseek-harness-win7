import {existsSync,readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {startAcpRun}=await load('packages/subagent/subagent-acp/src/run.ts'),{spawnSubprocess}=await load('packages/subprocess/subprocess-local/src/spawn.ts'),input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const scenario of input.cases){
 const children:any[]=[],errors:any[]=[],controller=new AbortController(),record=join(input.workspace,'source-'+scenario.name+'.jsonl'),ready=join(input.workspace,'source-'+scenario.name+'.ready'),spec={command:input.python,args:[input.peer],cwd:input.workspace,permission:scenario.policy??'reject',env:{...scenario.env,PROBE_RECORD:record,PROBE_READY:ready},disposeEofGraceMs:60,disposeGraceMs:100,spawn:(spec:any)=>{const child=spawnSubprocess(spec);children.push(child);return child},onError:(error:any,reason:any)=>errors.push(reason)}
 let handle:any,value:any={}
 try{
  try{
   handle=await startAcpRun({cwd:input.workspace,parent:{session:{header:{cwd:'intentionally-not-child-cwd'}}},signal:controller.signal,prompt:[{type:'image',source:{type:'url',url:'private'}},{type:'text',text:'explicit child task'}]},spec)
   if(scenario.cancel){const deadline=Date.now()+5000;while(!existsSync(ready)){if(Date.now()>deadline)throw Error('ACP peer readiness not observed');await new Promise(resolve=>setTimeout(resolve,10))}controller.abort()}
   value.result=await handle.result;const first=handle.dispose();value.sameDisposal=first===handle.dispose();await first;value.localAgentAbsent=handle.localAgent===undefined;value.distinctId=handle.id!=='same-child-id'
  }catch(error:any){value.error={name:error.name==='Error'?'RuntimeError':error.name,message:error.message}}
  value.quiescent=(await Promise.all(children.map(child=>child.waitForExit()))).every(Boolean);value.exitCodes=await Promise.all(children.map(async child=>(await child.done).exitCode))
  const packets=existsSync(record)?readFileSync(record,'utf8').trim().split('\n').filter(Boolean).map(line=>JSON.parse(line)):[]
  value.requests=packets.filter(packet=>'method' in packet&&packet.method!=='session/cancel').map(packet=>({method:packet.method,params:packet.params??{}}))
  value=JSON.parse(JSON.stringify(value).split(JSON.stringify(input.workspace).slice(1,-1)).join('$WORKSPACE'))
  rows.push({name:scenario.name,value,errorCount:errors.length,listeners:0})
 }finally{if(handle)await handle.dispose()}
}
process.stdout.write(JSON.stringify(rows))
