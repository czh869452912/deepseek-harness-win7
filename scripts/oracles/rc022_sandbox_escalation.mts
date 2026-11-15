import {load} from './rc022_subagent_fixture.mts'
const {validateEscalationArgs,approveEscalation}=await load('packages/sandbox/sandbox/src/escalation.ts'),rows:any[]=[]
const failure=(e:any)=>({error:e.message,code:e.code??null,errorName:e.name})
for(const [mode,reason] of [[undefined,undefined],['workspace-write',undefined],[undefined,'orphan'],['workspace-write','\ufeff\u3000'],['workspace-write','\u0085']]){try{validateEscalationArgs(mode,reason);rows.push({name:'validate',value:'valid'})}catch(error){rows.push({name:'validate',...failure(error)})}}
const cases:any[]=[]
for(const [effective,mode] of [['read-only','workspace-write'],['read-only','danger-full-access'],['workspace-write','read-only'],['danger-full-access','workspace-write'],['workspace-write','workspace-write']])for(const outcome of ['allowed-once','rejected','cancelled','unavailable'])cases.push([effective,mode,outcome,'both'])
cases.push(['read-only','workspace-write','allowed-once','no-service'],['read-only','workspace-write','allowed-once','no-agent'],['workspace-write','workspace-write','allowed-once','no-service'],['read-only','workspace-write','cancelled','aborted'],['read-only','workspace-write','unknown','both'])
for(const [effective,mode,outcome,composition] of cases){
 const seen:any[]=[],controller=new AbortController(),original=new Error('call cancelled'),agent={}
 const approver={request:async(ask:any)=>{seen.push({toolName:ask.toolName,callId:ask.callId,reason:ask.reason,displayReason:ask.displayReason,agent:ask.agent===agent,signal:ask.signal===controller.signal});return outcome}}
 if(composition==='aborted')controller.abort(original)
 const row:any={name:effective+'>'+mode+'/'+outcome+'/'+composition,asked:seen}
 try{row.value=await approveEscalation({effectiveMode:effective,requestedMode:mode,justification:'需要写入 "输出"\nverbatim',subject:'command'},{approver:composition==='no-service'?undefined:approver,agent:composition==='no-agent'?undefined:agent,toolName:'pwsh',callId:'call',signal:controller.signal})}catch(error){Object.assign(row,failure(error),{originalError:error===original})}
 rows.push(row)
}
console.log(JSON.stringify(rows))
