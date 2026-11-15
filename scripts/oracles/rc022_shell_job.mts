import {load} from './rc022_subagent_fixture.mts'
const {processJob,processOutcome,processSources,ringDelta}=await load('packages/shell/tool-pwsh/src/background.ts'),{renderPwshResult,renderPwshPromoted,renderPwshJobRead}=await load('packages/shell/tool-pwsh/src/render.ts'),rows:any[]=[]
for(const [status,exitCode,signal,sandbox] of [['completed',0,null,undefined],['completed',5,null,undefined],['killed',null,null,undefined],['killed',null,'SIGTERM',undefined],['completed',1,null,{mode:'read-only',denied:true}],['completed',1,null,{mode:'read-only',denied:true,runnerFailed:true}]])rows.push({name:'outcome',value:processOutcome({status,exitCode,signal,sandbox},['workspace-write'])})
for(const options of [{},{timedOut:true,exitCode:0},{stopped:'human',exitCode:1},{signal:'SIGINT',exitCode:null},{sandbox:{mode:'read-only',denied:true}}])rows.push({name:'foreground-render',text:renderPwshResult({exitCode:3,signal:null,timedOut:false,timeoutMs:10,stdout:{text:'out',truncated:true,spillPath:'C:/out'},stderr:{text:'err',truncated:true},...options},['workspace-write'])})
for(const output of ['','out','out\n'])rows.push({name:'promoted',text:renderPwshPromoted({jobId:'job',timeoutMs:10,output})})
for(const sandbox of [undefined,{mode:'read-only',denied:true},{mode:'workspace-write',denied:false,runnerFailed:true}])rows.push({name:'job-read',text:renderPwshJobRead('out',true,['a','b'],sandbox,['danger-full-access'])})
rows.push({name:'delta',text:ringDelta([{text:'out'},{text:'log',channel:'log'},{text:'err',channel:'stderr'}])})
let current:any;const sources=processSources(()=>current),before=sources.map((s:any)=>s.read(3));current={observed:Object.fromEntries(['stdout','stderr'].map(channel=>[channel,{readFrom:(offset:number)=>({text:channel,nextOffset:offset+6,lossy:true,spillPath:channel})}]))};rows.push({name:'sources',channels:sources.map((s:any)=>s.channel),before,after:sources.map((s:any)=>s.read(3))})
const drain=()=>new Promise(r=>setImmediate(r))
for(const when of ['preparation','running']){
 const gate=Promise.withResolvers<void>(),finished=Promise.withResolvers<void>(),trace:string[]=[],seen:any[]=[],process:any={status:'running',exitCode:null,signal:null,sandbox:undefined,done:finished.promise};process.kill=()=>{trace.push('kill');process.status='killed';finished.resolve()}
 const hooks=processJob(async(signal:any)=>{seen.push(signal);trace.push('start');await gate.promise;trace.push('prepared');return process},processOutcome)
 if(when==='running'){gate.resolve();await drain()}hooks.cancel('stop');hooks.cancel('again');if(when==='preparation')gate.resolve()
 const result=await hooks.done;rows.push({name:when,trace,result,aborted:seen[0].aborted,reason:seen[0].reason,failure:hooks.failure()??null})
}
for(const kind of ['prepare','cancel-prepare','process','thrown-value']){
 const gate=Promise.withResolvers<any>(),original=kind==='thrown-value'?0:new Error('original failure'),hooks=processJob(async()=>await gate.promise,processOutcome)
 if(kind==='cancel-prepare')hooks.cancel('stop')
 if(kind==='process'){const finished=Promise.withResolvers();gate.resolve({done:finished.promise,kill:()=>{}});await drain();finished.reject(original)}else gate.reject(original)
 const result=await hooks.done,failure=hooks.failure();rows.push({name:kind,result,originalError:failure!==undefined&&failure.error===original})
}
console.log(JSON.stringify(rows))
