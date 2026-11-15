import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=readFileSync(process.argv[3]!,'utf8'),{ctx}=await setup(join(workspace,'source')),{default:Jobs}=await load('packages/jobs/jobs-local/src/index.ts'),owner=await ctx.plugin(Jobs,{retainBytes:12,settledRetainBytes:4,pumpPollMs:10000,maxConcurrentJobsPerOwner:1}),jobs=ctx.jobs,rows:any[]=[],events:any[]=[],producer=new Map<string,any>(),handles:any[]=[]
const agent=(await ctx.agents.create({sessionId:'root',agentOptions:{provider:'script',model:'model'}})).agent
jobs.events.subscribe({owners:'all'},(event:any)=>events.push(event))
const run=(handle:any)=>{handles.push(handle);handle.append('seed',{channel:'meta'});handle.updateProgress('preparing');const future=Promise.withResolvers();producer.set(handle.id,future);return {done:future.promise,cancel:()=>future.resolve({status:'killed',detail:'stopped'})}}
const call=(name:string,fn:()=>any)=>{try{rows.push({name,value:fn()})}catch(error){const e=error as any;rows.push({name,error:e.message,code:e.code??null})}}
try{
 call('no-controller',()=>jobs.start({kind:'pwsh',label:'test',owner:'root',run}));jobs.attachController('test')
 call('unknown-owner',()=>jobs.start({kind:'pwsh',label:'test',owner:'missing',run}))
 const id=jobs.start({kind:'pwsh',label:'test',owner:'root',toolCall:{callId:'call',toolName:'pwsh'},run})
 call('initial',()=>jobs.get(id,'root'));call('foreign',()=>jobs.get(id,'other'));call('limit',()=>jobs.start({kind:'pwsh',label:'second',owner:'root',run}))
 const handle=handles.at(-1);handle.append('你好',{channel:'stdout'});handle.append('tail',{channel:'stderr'});handle.updateProgress('working')
 call('ui-read',()=>jobs.readAt(id,0,'root'));call('model-read',()=>jobs.read(id,'root'));call('second-read',()=>jobs.read(id,'root'))
 handle.append('final',{channel:'stdout'});const waiting=jobs.wait(id,10000,'root');producer.get(id).resolve({status:'completed',detail:'exit code: 0',result:{summary:'done'}});await waiting;await new Promise(r=>setImmediate(r))
 call('terminal-ui',()=>jobs.readAt(id,0,'root'));call('terminal-model',()=>jobs.read(id,'root'));call('result-once',()=>jobs.read(id,'root'))
 handle.append('ignored');handle.updateProgress('ignored');call('terminal-kill',()=>jobs.kill(id,'root','late'));jobs.remove(id,'root');call('missing',()=>jobs.get(id,'root'))
 rows.push({name:'events',events});rows.push({name:'durable',events:agent.session.snapshotEvents().filter((event:any)=>event.type.startsWith('job/')).map((event:any)=>({type:event.type,data:event.data}))})
 await edges()
 const normalize=(value:any):any=>typeof value==='string'?value.replace(/pwsh-[0-9a-f]{16}/g,'<job>'):Array.isArray(value)?value.map(normalize):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,item])=>[key,['startedAt','finishedAt'].includes(key)?0:normalize(item)])):value
 console.log(JSON.stringify(normalize(rows)))
}finally{for(const future of producer.values())future.resolve({status:'killed'});await owner.dispose();await ctx.fiber.dispose()}

async function edges(){
 const acall=async(name:string,operation:Promise<any>)=>{try{rows.push({name,value:await operation})}catch(error){const e=error as Error;rows.push({name,error:e.message,errorName:e.name})}}
 let future=Promise.withResolvers<any>();const attempts:any[]=[]
 let id=jobs.start({kind:'pwsh',label:'retry',run:()=>({done:future.promise,cancel:(reason:any)=>{attempts.push(reason);if(attempts.length===1)throw new Error('retry me');future.resolve({status:'killed',detail:'signal: SIGTERM'})}})})
 try{jobs.kill(id,undefined,'first')}catch(error){rows.push({name:'cancel-throw',error:(error as Error).message,status:jobs.get(id).status})}
 let controller=new AbortController(),waiting=jobs.wait(id,10000,undefined,controller.signal);controller.abort();await acall('wait-abort',waiting)
 rows.push({name:'wait-timeout',status:(await jobs.wait(id,1)).status});jobs.kill(id,undefined,'second');await jobs.wait(id,10000);rows.push({name:'retry-killed',job:jobs.get(id),attempts});jobs.remove(id)
 future=Promise.withResolvers<any>();id=jobs.start({kind:'pwsh',label:'reject',run:()=>({done:future.promise,cancel:()=>{}})});future.reject(new Error('producer rejected'));await jobs.wait(id,10000);rows.push({name:'rejected-producer',job:jobs.get(id)});jobs.remove(id)
 future=Promise.withResolvers<any>();id=jobs.start({kind:'pwsh',label:'abort-on-settle',run:()=>({done:future.promise,cancel:()=>{}})});controller=new AbortController();const seen:any[]=[]
 let detach=jobs.events.subscribe({owners:'all'},(event:any)=>{if(event.type==='settled'){seen.push(event.awaited);controller.abort()}})
 waiting=jobs.wait(id,10000,undefined,controller.signal);future.resolve({status:'completed'});await acall('settle-wins-abort',waiting);detach();jobs.remove(id);rows.push({name:'settle-awaited',value:seen})
 future=Promise.withResolvers<any>();id=jobs.start({kind:'pwsh',label:'orphan',run:()=>({done:future.promise,cancel:()=>{throw new Error('cannot cancel')}})});const observed:any[]=[]
 detach=jobs.events.subscribe({owners:'all'},(event:any)=>{if(['settled','removed'].includes(event.type))observed.push(event)})
 await jobs.disposeAll();future.resolve({status:'completed',detail:'too late'});await new Promise(r=>setImmediate(r));detach();rows.push({name:'teardown-first-wins',events:observed,jobs:jobs.list()})
}
