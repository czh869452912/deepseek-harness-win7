import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {createRequire} from 'node:module'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),fixture=await setup(join(workspace,'source')),ctx=fixture.ctx,rows:any[]=[],aborters:AbortController[]=[],queries:any[]=[]
const {ListenerBuffer,EventListener,eventItem}=await load('packages/api/session-controller/src/history/listener.ts'),{HistoryController}=await load('packages/api/session-controller/src/history/controller.ts'),{z}=createRequire(join(process.argv[2]!,'packages/session/session-projection/package.json'))('zod')
const signal=()=>{const abort=new AbortController();aborters.push(abort);return abort},next=async(stream:any)=>{const result=await stream.next();return result.done?{done:true}:{value:result.value}},query=ctx.sessionQuery.observeSession.bind(ctx.sessionQuery)
ctx.sessionQuery.observeSession=async(...args:any[])=>{queries.push(true);return query(...args)}
try{
 let buffer=new ListenerBuffer(ctx,signal().signal);const calls:any[]=[],numbers=buffer.createInput((value:any)=>{calls.push(value);return ['n:'+value]}),words=buffer.createInput((value:any)=>[value])
 numbers.append(2);words.prepend('first');rows.push({name:'lazy',calls:[...calls]})
 let values=buffer.items()[Symbol.asyncIterator]();rows.push({name:'heterogeneous',values:[await next(values),await next(values)],calls:[...calls]})
 try{await buffer.items()[Symbol.asyncIterator]().next()}catch(error:any){rows.push({name:'single-consumer',code:error.code})}
 numbers.append(3);rows.push({name:'wake',value:await next(values)});await values.return?.()
 const closed:string[]=[];buffer.capture(()=>closed.push('captured'));buffer.own(()=>closed.push('owned'));numbers.append(4)
 try{buffer.createInput((value:any)=>[value])}catch(error:any){rows.push({name:'closed',actions:closed,message:error.message})}
 const failure=new Error('captured');buffer=new ListenerBuffer(ctx,signal().signal);buffer.capture(()=>{throw failure})
 try{await buffer.items()[Symbol.asyncIterator]().next()}catch(error:any){rows.push({name:'captured-failure',same:error===failure,message:error.message})}
 buffer=new ListenerBuffer(ctx,signal().signal);buffer.createInput(function*(value:any){buffer[Symbol.dispose]();yield value}).append(1);rows.push({name:'close-during-transform',value:await next(buffer.items()[Symbol.asyncIterator]())})
 const history=new HistoryController(ctx);let abort=signal(),stream=history.observeEvent({address:{kind:'session',sessionId:'later'}},abort.signal)[Symbol.asyncIterator]()
 rows.push({name:'ready-missing',value:await next(stream),queries:queries.length})
 const session=ctx.sessions.create('later',{meta:{cwd:'C:/listeners'}});session.append('fixture/tick',{value:0},{ignorable:true})
 rows.push({name:'created-after-ready',value:await next(stream)});abort.abort();rows.push({name:'cancel-event',value:await next(stream)})
 abort=signal();let listener=new EventListener(ctx,session.id,abort.signal)
 session.append('fixture/tick',{value:1},{ignorable:true});session.append('fixture/tick',{value:2},{ignorable:true});listener.setCursor(1);ctx.emit('session/created',session)
 const events=listener.events()[Symbol.asyncIterator]();rows.push({name:'creation-cut',value:await next(events)})
 session.append('fixture/tick',{value:3},{ignorable:true});rows.push({name:'deduplicated-suffix',value:await next(events)});await events.return?.()
 try{eventItem({type:'event',session,event:session.snapshotEvents()[2]},1)}catch(error:any){rows.push({name:'gap',code:error.code,message:error.message})}
 const external=new ListenerBuffer(ctx,signal().signal);listener=new EventListener(ctx,session.id,fixture.signal,external);listener.setCursor(-1);ctx.emit('session/created',session)
 values=external.items()[Symbol.asyncIterator]();const first=await next(values);listener[Symbol.dispose]();external[Symbol.dispose]();rows.push({name:'external-batch-disposal',first,rest:await next(values)})
 for(const [key,multiplier] of [['ticks',1],['doubleTicks',2]] as const)await ctx.sessionProjections.register({key,stateVersion:1,stateSchema:z.number().int(),init:()=>0,apply:(state:number,event:any)=>event.type==='fixture/tick'?state+multiplier:state,wire:{viewSchema:z.number().int(),view:(state:number)=>state}})
 abort=signal();const changes=history.observeProjections({sessionId:'later'},abort.signal)[Symbol.asyncIterator]();rows.push({name:'projection-ready',value:await next(changes),queries:queries.length})
 const other=ctx.sessions.create('other',{meta:{cwd:'C:/listeners'}});other.append('fixture/tick',{value:100},{ignorable:true});session.append('fixture/tick',{value:4},{ignorable:true});rows.push({name:'grouped-projection',value:await next(changes)})
 session.append('fixture/tick',{value:5},{ignorable:true});abort.abort();rows.push({name:'cancel-discards-queued-projection',value:await next(changes)})
 const provider=ctx.plugin((child:any)=>{child.provide('historyFixture',new HistoryController(child))});await provider
 const owned=ctx.historyFixture.observeEvent({address:{kind:'session',sessionId:'later'}},fixture.signal)[Symbol.asyncIterator]();await owned.next();const waiting=next(owned);await provider.dispose()
 rows.push({name:'unload-wakes-reader',value:await waiting,queries:queries.length})
}finally{for(const abort of aborters)abort.abort();await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows,(_key,value)=>value&&typeof value==='object'&&'type'in value&&'seq'in value&&'time'in value?{...value,time:0}:value))
