import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),fixture=await setup(join(workspace,'source')),ctx=fixture.ctx,rows:any[]=[],pending:any[]=[],streams:any[]=[],aborters:AbortController[]=[],tasks:Promise<any>[]=[]
const {HistoryController}=await load('packages/api/session-controller/src/history/controller.ts'),{StateController}=await load('packages/api/session-controller/src/state/controller.ts'),{appendPluginRecord}=await load('packages/core/session/src/index.ts')
ctx.provide('typertGateway',{getPendingRemoteEvents:()=>pending})
const history=new HistoryController(ctx),state=new StateController(ctx,history),signal=fixture.signal
const message=(id:string)=>({id,role:'user',content:[{type:'text',text:id}],source:{kind:'user'}}),add=(event:string,agentId='state')=>pending.push({event,agentId})
const result=(v:any)=>({reason:v.reason,active:v.state.active,running:v.state.running,pendingInput:v.state.pendingInput,outputRecords:v.output.records.length,truncated:v.output.truncated})
try{
 const handle=await ctx.agents.create({sessionId:'state',meta:{cwd:'C:/state'},agentOptions:{provider:'script',model:'model'}}),agent=handle.agent,request={sessionId:'state'}
 rows.push({name:'live-idle',value:await state.state(request,signal)})
 const queued=message('queued'),steering:any=message('steer'),context:any=message('context');steering.source.rpcId='rpc';context.source={kind:'user-approval'}
 agent.inbox.append('next-turn',queued);agent.inbox.append('next-step',steering);agent.inbox.append('next-step',context)
 rows.push({name:'queue',value:(await state.state(request,signal)).queue})
 add('approval/request');add('user-questions/request');add('custom/request');add('approval/request');add('ignored','other')
 rows.push({name:'pending',value:(await state.state(request,signal)).pendingInput});rows.push({name:'input-before-idle',value:result(await state.wait(request,signal))})
 pending.length=0;agent.inbox.clear();rows.push({name:'active-idle-wait',value:result(await state.wait(request,signal))})
 const abort=new AbortController();aborters.push(abort);const states=state.observeState(request,abort.signal)[Symbol.asyncIterator]();streams.push(states);await states.next()
 appendPluginRecord(agent.session,'plugin:fixture/tick',{n:1});appendPluginRecord(agent.session,'plugin:fixture/tick',{n:2})
 const value=(await states.next()).value;rows.push({name:'coalesced',cursor:value.cursor,expected:agent.session.seq-1})
 const read=states.next();tasks.push(read);await Promise.resolve();abort.abort();rows.push({name:'observe-cancel',ended:(await read).done});await states.return?.()
 agent.followup(message('run'))
 // Bind to actual reconnect state so both runtimes wait for the same partial response cut.
 const {ListenerBuffer}=await load('packages/api/session-controller/src/history/listener.ts'),queue=new ListenerBuffer(ctx,signal),listener=(history as any).streamsListener.bind(agent.id,signal,queue)
 try{while(listener.snapshot().baseline.activeAttempt?.nextIndex<2||listener.snapshot().baseline.activeAttempt===undefined)await new Promise(resolve=>setTimeout(resolve,0))}finally{listener[Symbol.dispose]();queue[Symbol.dispose]()}
 rows.push({name:'running-timeout',value:result(await state.wait({...request,timeoutMs:25},signal)),stillRunning:agent.status==='running',callerAborted:signal.aborted})
 const cancel=new AbortController();aborters.push(cancel);const task=state.wait(request,cancel.signal);tasks.push(task);await Promise.resolve();const primary=new Error('caller cancelled');cancel.abort(primary)
 try{await task}catch(error){rows.push({name:'caller-cancel',same:error===primary,stillRunning:agent.status==='running'})}
 const polled=state.wait({...request,timeoutMs:2500},signal);tasks.push(polled);await Promise.resolve();add('user-questions/request')
 rows.push({name:'pending-periodic',value:result(await polled),stillRunning:agent.status==='running'})
 pending.length=0;agent.cancel();await agent.whenIdle();rows.push({name:'after-execution',value:result(await state.wait(request,signal))});await handle.dispose()
 rows.push({name:'cold-state',value:await state.state(request,signal),agentAbsent:ctx.agents.get('state')===undefined});rows.push({name:'cold-wait',value:result(await state.wait(request,signal))})
 for(const bound of [{afterSeq:-2},{afterSeq:-0},{maxMessages:0},{timeoutMs:0},{timeoutMs:2147483648},{timeoutMs:1.5}]){try{await state.wait({...request,...bound},signal)}catch(error:any){rows.push({name:'bounds',bound,code:error.code})}}
 try{await state.state({sessionId:'missing'},signal)}catch(error:any){rows.push({name:'missing',code:error.code})}
}finally{for(const abort of aborters)abort.abort();await Promise.allSettled(tasks);for(const stream of streams)await stream.return?.();await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
