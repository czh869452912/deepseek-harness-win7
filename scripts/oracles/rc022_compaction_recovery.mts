import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Session}=await load('packages/core/session/src/index.ts')
const {compactSurfaceRegion}=await load('packages/compaction/compaction-basic/src/region.ts')
const cases=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows=[]
const message=(id:string,text:string)=>({id,role:'user',source:{kind:'human'},content:[{type:'text',text}]})
function failure(error:any):any {
 return {message:error.message,...error.code===undefined?{}:{code:error.code},...error.cause===undefined?{}:{cause:failure(error.cause)}}
}
for(const test of cases){
 const session=Session.create('session'),trace:any[]=[]
 session.append('user/message',message('selected','selected'),{surfaceOp:'append'})
 session.append('user/message',message('outside','outside'),{surfaceOp:'append'})
 const extra=test.extra
 if(!test.manual&&extra!=='no-turn'||extra==='busy')session.append('turn/start',{turn:1})
 if(extra==='locked')session.append('compaction/start',{compactionId:'held',turn:null})
 const controller=new AbortController();let price=100,calls=0
 const meter={measure(subject:any){
  const nodes=subject.surface.nodes.map((seq:number)=>({seq,tokens:seq===0?price:100,heuristicTokens:50}))
  if(extra==='stale')nodes[0].seq=99
  return {nodes}
 },estimateMessage(){return extra==='large'?100:1}}
 const dependencies={meter,async summarize(data:any){
  calls++;trace.push({summary:data})
  if(calls===1){
   if(test.mutation==='append')session.append('user/message',message('added','added'),{surfaceOp:'append'})
   else if(['outside','rewrite'].includes(test.mutation)){
    const seq=test.mutation==='outside'?1:0
    session.append('user/message',message('rewritten','rewritten'),{surfaceOp:{op:'replace',startSeq:seq,endSeq:seq},sourceEventSeqs:[seq]})
   }else if(test.mutation==='reprice')price++
   if(extra==='cancel-summary')controller.abort(new Error('cancelled by caller'))
   if(test.retry)throw new Error('first summary failed')
  }
  return {summary:[{type:'text',text:'checkpoint'}],provider:'test',model:'model'}
 },recover(error:any,_agent:any,selected:any){
  trace.push({recover:[...selected],message:error.message})
  if(extra==='cancel-recovery')controller.abort(new Error('cancelled by caller'))
  return true
 }}
 const row:any={case:test,trace}
 try{
  const {compactionId,...result}=await compactSurfaceRegion(dependencies,session,0,0,{session},
   {owner:test.manual?null:'current-turn',stability:test.manual?'selected-span':'whole-surface',sourceCommandId:'command',
    flush:async()=>{trace.push('flush');if(extra==='flush')throw new Error('disk unavailable')}},controller.signal)
  row.result=result
 }catch(error){row.error=failure(error)}
 const events=session.snapshotEvents()
 row.nodes=[...session.surface.nodes]
 row.events=events.map((event:any)=>({seq:event.seq,type:event.type,
  ...event.surfaceOp===undefined?{}:{surfaceOp:event.surfaceOp},...event.sourceEventSeqs===undefined?{}:{sourceEventSeqs:event.sourceEventSeqs}}))
 row.checkpoints=events.filter((event:any)=>event.type==='user/message'&&event.data.source.kind==='compact-checkpoint').map((event:any)=>{
  const {compactionId,...source}=event.data.source
  return {content:event.data.content,source,identity:compactionId===events.find((item:any)=>item.type==='compaction/start').data.compactionId}
 })
 rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
