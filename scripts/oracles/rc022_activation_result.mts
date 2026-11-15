import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {ActivationPool,ChildLock,captureLocalResult,requireLocalActivation}=await load('packages/subagent/subagent/src/activation.ts'),messages=await load('packages/subagent/subagent/src/continuation-messages.ts')
const rows:any[]=[],pool=new ActivationPool(),releases=[pool.reserve(2),pool.reserve(2)]
try{pool.reserve(2)}catch(error:any){rows.push({kind:'capacity',code:error.code,message:error.message})}
releases[0]();releases[0]();const third=pool.reserve(2);releases[0]();try{pool.reserve(2)}catch(error:any){rows.push({kind:'stale-release',code:error.code})}
third();releases[1]();pool.reserve(1)();rows.push({kind:'released',remaining:pool['slots'].size})
const locks=new ChildLock(),trace:string[]=[],entered=Promise.withResolvers<void>(),release=Promise.withResolvers<void>()
const one=locks.run('child',async()=>{trace.push('first');entered.resolve();await release.promise;trace.push('failed');throw Error('first failure')}),two=locks.run('child',async()=>{trace.push('second');return 2})
await entered.promise;const other=await locks.run('other',async()=>{trace.push('other');return 3});release.resolve();const results=await Promise.allSettled([one,two])
rows.push({kind:'locks',trace,first:(results[0] as any).reason.message,second:(results[1] as any).value,other,remaining:locks['tails'].size})
for(const reason of ['completed','aborted','interrupted','error','blocked','max-tokens','custom']){
 const events=[{type:'assistant/message',data:{message:{content:[{type:'text',text:'seed'}]},stream:[]}},{type:'turn/start',data:{turn:1}},{type:'step/start',data:{turn:1,step:1}},
 {type:'assistant/message',data:{message:{content:[{type:'text',text:'answer'}]},stream:[]}},{type:'assistant/message',data:{message:{content:[]},stream:[]}},{type:'turn/end',data:{turn:1,reason:{kind:reason}}}]
 let a:any
 for(const structured of ['none','missing','null']){a={handle:{agent:{session:{snapshotEvents:(cut:number)=>events.slice(cut)}}},outputStart:1,failureAt:undefined,structured:structured==='none'?undefined:{captured:()=>structured==='missing'?undefined:{value:null}}};rows.push({kind:'capture',reason,structured,value:captureLocalResult(a)})}
 a.failureAt=0;rows.push({kind:'failure',reason,value:captureLocalResult(a)})
}
for(const reason of ['completed','aborted','max-tokens','refusal','error','custom'])for(const continuable of [true,false])for(const omit of [true,false]){
 const terminal={stopReason:reason,output:[{type:'text',text:''},{type:'image',image:'x'},{type:'text',text:'answer'}],structured:{result:null},diagnostic:'detail'},value=messages.createSettlementMessage('child','worker/nested',terminal,continuable,omit);const {id:_id,...notice}=value
 rows.push({kind:'notice',reason,continuable,omit,value:notice})
}
const relay=messages.createAgentMessage({id:'child'},'worker',[{type:'text',text:'hello'}]);const {id:_relayId,...relayValue}=relay;rows.push({kind:'relay',value:relayValue,guidance:messages.withResultDeliveryGuidance([])})
const bounded=messages.createSettlementMessage('child','😀'.repeat(80),{stopReason:'completed',output:[]});const {id:_boundedId,...boundedValue}=bounded;rows.push({kind:'bounded',value:boundedValue})
try{requireLocalActivation({kind:'external',childId:'external'})}catch(error:any){rows.push({kind:'external',code:error.code,message:error.message})}
process.stdout.write(JSON.stringify(rows))
