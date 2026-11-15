import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {setup,load} from './rc022_subagent_fixture.mts'
const workspace=readFileSync(process.argv[3]!,'utf8'),{ctx}=await setup(join(workspace,'source'))
await ctx.plugin((await load('packages/jobs/jobs-local/src/index.ts')).default);await ctx.plugin(await load('packages/jobs/tool-jobs/src/index.ts'),{completionDelivery:'quiet',inlineOutputBytes:512})
const {executeToolFixture}=await load('packages/test-support/tool-testkit/src/index.ts'),{createUserMessage}=await load('packages/llm/llm/src/index.ts'),lease=await ctx.agents.create({sessionId:'root',agentOptions:{provider:'script',model:'model'}}),agent=lease.agent,rows:any[]=[],futures:any[]=[]
let counter=0
const call=async(name:string,args:any)=>{const result=await executeToolFixture(ctx,{callId:'call-'+(++counter),name,arguments:args,agent,signal:new AbortController().signal});return {isError:result.isError,value:result.value??null,content:result.content}}
const drain=()=>new Promise(r=>setImmediate(r))
const start=(label:string,limit?:number)=>{const future=Promise.withResolvers<any>();futures.push(future);const holder:any[]=[];const id=ctx.jobs.start({kind:'pwsh',label,owner:agent.id,...limit===undefined?{}:{outputLimitBytes:limit},run:(handle:any)=>{holder.push(handle);return {done:future.promise,cancel:()=>future.resolve({status:'killed'})}}});return {id,future,holder}}
const notices=()=>agent.inbox.nextStep.filter((m:any)=>m.source.kind==='tool-jobs').map((m:any)=>({content:m.content,source:m.source}))
try{
 let {id,future,holder}=start('stream');let handle=holder[0];handle.append('out');handle.append('err',{channel:'stderr'});handle.append('hidden',{channel:'log'});handle.updateProgress('building')
 rows.push({name:'list-progress',value:await call('job_list',{})});rows.push({name:'live-read',value:await call('job_output',{job_id:id})})
 future.resolve({status:'completed',result:'FINAL'});await drain();rows.push({name:'inline-notice',notices:notices()});rows.push({name:'held-read',value:await call('job_output',{job_id:id}),notices:notices()});rows.push({name:'repeat-read',value:await call('job_output',{job_id:id})});ctx.jobs.remove(id,agent.id)
 ;({id,future,holder}=start('large-result'));holder[0].append('head\n');future.resolve({status:'completed',result:'R'.repeat(700)});await drain();rows.push({name:'overflow-notice',notices:notices()});rows.push({name:'overflow-held',value:await call('job_output',{job_id:id}),notices:notices()});ctx.jobs.remove(id,agent.id)
 ;({id,future,holder}=start('logged'));holder[0].append('one time');future.resolve({status:'completed'});await drain();const notice=agent.inbox.nextStep.find((m:any)=>m.source.kind==='tool-jobs');agent.session.append('user/message',notice,{surfaceOp:'append'});agent.inbox.remove(notice.id);rows.push({name:'logged-inline',value:await call('job_output',{job_id:id})});ctx.jobs.remove(id,agent.id)
 for(const limit of [1,7,8,16,40,64,100,300]){({id,future,holder}=start('  第一行\nsecond',limit));holder[0].append('你好'.repeat(100));future.resolve({status:'completed',result:'R'.repeat(700)});await drain();rows.push({name:'cap-'+limit,notices:notices(),value:await call('job_output',{job_id:id})});ctx.jobs.remove(id,agent.id)}
 ;({id,future,holder}=start('steer'));holder[0].append('ready');holder[0].updateProgress('working');rows.push({name:'timeout',value:await call('job_output',{job_id:id,wait:true,timeout_ms:1})})
 const waiting=call('job_output',{job_id:id,wait:true,timeout_ms:10000});await drain();agent.inject(createUserMessage({content:[{type:'text',text:'steer'}],source:{kind:'user'}}));rows.push({name:'steered',value:await waiting,progress:ctx.jobs.get(id,agent.id).progress})
 rows.push({name:'kill',value:await call('job_kill',{job_id:id,reason:'done'})});await ctx.jobs.wait(id,10000,agent.id);await drain();rows.push({name:'no-kill-notice',notices:notices()});ctx.jobs.remove(id,agent.id)
 const normalize=(value:any):any=>typeof value==='string'?value.replace(/pwsh-[0-9a-f]{16}/g,'<job>'):Array.isArray(value)?value.map(normalize):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,item])=>[key,['startedAt','finishedAt'].includes(key)?0:normalize(item)])):value
 console.log(JSON.stringify(normalize(rows)))
}finally{for(const future of futures)future.resolve({status:'killed'});await lease.dispose();await ctx.fiber.dispose()}
