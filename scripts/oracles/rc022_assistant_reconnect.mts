import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),fixture=await setup(join(workspace,'source')),ctx=fixture.ctx,rows:any[]=[],abort=new AbortController()
const {HistoryController}=await load('packages/api/session-controller/src/history/controller.ts'),{ListenerBuffer}=await load('packages/api/session-controller/src/history/listener.ts')
try{
 const history=new HistoryController(ctx),streams=history.streamsListener,session=ctx.sessions.create('target',{meta:{cwd:'C:/reconnect'}}),agent={id:session.id,session},queue=new ListenerBuffer(ctx,abort.signal),listener=streams.bind(session.id,abort.signal,queue),emit=(frame:any)=>ctx.emit('agent/assistant-stream',{agent,frame}),start={type:'start',attemptId:'attempt',revision:1,turn:1,step:1}
 rows.push({name:'empty',value:listener.snapshot()});emit(start);const opening=listener.snapshot();listener.setOrdinalCut(opening.ordinal)
 rows.push({name:'opening',value:opening,stable:listener.snapshot().baseline===opening.baseline})
 const chunk={type:'chunk',attemptId:'attempt',revision:2,index:0,time:4,chunk:{type:'text-delta',index:0,text:'partial'}};emit(chunk)
 rows.push({name:'chunk-baseline',value:listener.snapshot(),old:opening})
 const secondQueue=new ListenerBuffer(ctx,abort.signal),second=streams.bind(session.id,abort.signal,secondQueue)
 rows.push({name:'second-connection',value:second.snapshot(),shared:second.snapshot().baseline===listener.snapshot().baseline})
 const end={type:'end',attemptId:'attempt',revision:3,index:1,outcome:{kind:'abandoned'}};emit(end)
 const values=queue.items()[Symbol.asyncIterator](),secondValues=secondQueue.items()[Symbol.asyncIterator]()
 rows.push({name:'uncovered-frames',values:[(await values.next()).value,(await values.next()).value],second:(await secondValues.next()).value})
 ctx.emit('agent/disposed',{agent});rows.push({name:'disposed-baseline',value:listener.snapshot()})
 session.append('fixture/tick',{value:1},{ignorable:true});emit({...start,attemptId:'new'})
 rows.push({name:'new-lifecycle',baseline:listener.snapshot(),wire:(await values.next()).value})
 emit({...chunk,attemptId:'new',revision:3,index:9});rows.push({name:'gap-clears-attempt',value:listener.snapshot()})
 second[Symbol.dispose]();secondQueue.createInput((value:any)=>[{marker:value}]).append('still-open')
 rows.push({name:'unbound-queue',value:(await secondValues.next()).value,closed:secondQueue.closed})
 listener[Symbol.dispose]();abort.abort();rows.push({name:'cancelled',ended:[(await values.next()).done,(await secondValues.next()).done]})
}finally{abort.abort();await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
