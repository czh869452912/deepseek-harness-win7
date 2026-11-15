import {load} from './rc022_subagent_fixture.mts'
const {OutputRing}=await load('packages/jobs/jobs-local/src/ring.ts'),{startPump}=await load('packages/jobs/jobs-local/src/pump.ts'),rows:any[]=[]
for(const cap of [0,1,2,3,4,7,16,64]){
 const ring=new OutputRing(),snapshots:any[]=[]
 for(const [text,options] of [['',undefined],['abc',undefined],['你好',{channel:'stdout'}],['😀z',{channel:'stderr',gapBefore:true}],['x'.repeat(90),undefined],['e\u0301',{channel:'meta'}],['\ud800',undefined]] as const){
  const changed=ring.append(text,options,cap)
  snapshots.push({changed,retained:ring.retainedBytes,total:ring.total,earliest:ring.earliest,reads:[0,1,4,ring.total-1,ring.total,ring.total+1].map(offset=>ring.readFrom(offset))})
 }
 const read=ring.readFrom(0);if(read.chunks.length)read.chunks[0].text='mutated';ring.trim(1);snapshots.push({read:ring.readFrom(0)})
 rows.push({name:'ring',cap,snapshots})
}
for(const rejection of [false,true]){
 const trace:any[]=[],until=Promise.withResolvers<void>(),state={final:false}
 const source=(channel:string)=>({channel,read:(cursor:number)=>{trace.push({read:channel,cursor});return {text:(state.final?'tail-':'head-')+channel,nextOffset:state.final?20:10,lossy:state.final,...state.final?{}:{spillPath:'spill-'+channel}}}})
 const sink={append:(text:string,options?:any)=>trace.push({append:text,options:options??null}),spill:(index:number,path?:string)=>trace.push({spill:index,path:path??null})}
 const pump=startPump([source('stdout'),source('stderr')],sink,10000,until.promise);state.final=true
 if(rejection)until.reject(Error('producer rejected'));else until.resolve()
 await pump.done;rows.push({name:'pump',rejection,trace})
}
console.log(JSON.stringify(rows))
