import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {settleRunResult,subprocessRunHandle,assertPositiveFinite}=await load('packages/subagent/subagent/src/out-of-process.ts'),rows:any[]=[]
for(const input of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const signal=new AbortController().signal,removed:any[]=[],reports:any[]=[],original=signal.removeEventListener.bind(signal),onAbort=()=>{}
 signal.removeEventListener=(...args:any[])=>{removed.push(args[0]);original(...args)};signal.addEventListener('abort',onAbort)
 const result=await settleRunResult({attempt:async()=>{await Promise.resolve();if(input.fails)throw Error('private failure');return {output:[{type:'text',text:'finished'}],stopReason:'completed',...input.diagnostic===null?{}:{diagnostic:input.diagnostic}}},cancelled:()=>input.cancelled,
  collectOutput:()=>[{type:'text',text:'partial'}],collectDiagnostic:()=>input.diagnostic??undefined,onError:(error:any,reason:any)=>{reports.push([error.message,reason]);if(input.sinkThrows)throw Error('sink failed')},signal,onAbort})
 rows.push({kind:'result',value:result,reports,removed})
}
for(const fails of [false,true]){
 const controller=new AbortController(),trace:string[]=[],gate=Promise.withResolvers<void>(),failure=Error('teardown failed'),onAbort=()=>{}
 controller.signal.addEventListener('abort',onAbort)
 const handle=subprocessRunHandle({id:'external',result:Promise.resolve({output:[],stopReason:'completed'}),signal:controller.signal,onAbort,requestCancel:()=>trace.push('cancel'),teardown:async()=>{trace.push('teardown');await gate.promise;if(fails)throw failure;trace.push('exited')}})
 const first=handle.dispose(),second=handle.dispose(),before=[...trace];gate.resolve();const observed=await Promise.allSettled([first,second])
 rows.push({kind:'dispose',same:first===second,before,after:trace,errorIdentity:!fails||observed.every(r=>r.status==='rejected'&&r.reason===failure)})
}
for(const value of [0,-1,true,1,1.5,Infinity,NaN]){let result:any;try{assertPositiveFinite('backend','timeout',value);result=true}catch(error:any){result=error.message}rows.push({kind:'timing',value:result})}
process.stdout.write(JSON.stringify(rows))
