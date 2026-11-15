import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),{ctx}=await setup(join(workspace,'source'),workspace),{HarnessSdkJsonRpcServer}=await load('packages/sdk/server/src/server.ts'),server=new HarnessSdkJsonRpcServer(ctx,{notify(){}}),rows:any[]=[]
async function call(method:string,params:any){try{return {value:await server.handleRequest('session/'+method,params)}}catch(error:any){return {error:error.message,name:error.name}}}
function record(name:string,result:any){rows.push({name,result})}
try{
 for(const method of ['resume','wait'])record('before-'+method,await call(method,{sessionId:'a'}))
 await server.initialize({cwd:workspace,provider:'script',model:'model'})
 for(const [name,method,params] of [['resume-id','resume',{}],['resume-empty','resume',{sessionId:''}],['wait-id','wait',{}],['wait-empty','wait',{sessionId:''}],['wait-unknown','wait',{sessionId:'unknown'}],['resume-missing','resume',{sessionId:'missing'}]] as const)record(name,await call(method,params))
 const handle=await ctx.agents.create({sessionId:'persisted',meta:{cwd:workspace},agentOptions:{provider:'script',model:'model'}});await ctx.workingDirectory.set(handle.agent,join(workspace,'child'))
 handle.agent.session.append('turn/start',{turn:1});handle.agent.session.append('turn/end',{turn:1,reason:{kind:'completed'}});await handle.dispose()
 record('resume',await call('resume',{sessionId:'persisted',ignored:true}));const agent=server.sessions.get('persisted').handle.agent
 rows.push({name:'restored',id:agent.id,cwd:await ctx.workingDirectory.ensure(agent),origin:agent.session.header.cwd,model:agent.model.current()})
 record('resume-owned',await call('resume',{sessionId:'persisted'}));record('wait-owned',await call('wait',{sessionId:'persisted'}))
 ctx.emit('agent/error',{agent,error:Error('active failure')});record('failure',await call('wait',{sessionId:'persisted'}))
 agent.session.append('turn/start',{turn:2});agent.session.append('turn/end',{turn:2,reason:{kind:'completed'}});record('after-terminal',await call('wait',{sessionId:'persisted'}))
 const outsider=await ctx.agents.create({sessionId:'outsider',agentOptions:{provider:'script',model:'model'}});ctx.emit('agent/error',{agent:outsider.agent,error:Error('unowned')});record('unowned',await call('wait',{sessionId:'outsider'}))
 const child=await ctx.agents.create({sessionId:'child',meta:{parentSession:'persisted',origin:'subagent'},agentOptions:{provider:'script',model:'model'}});child.agent.session.append('turn/start',{turn:1});child.agent.session.append('turn/end',{turn:1,reason:{kind:'completed'}});await child.dispose();record('resume-child',await call('resume',{sessionId:'child'}))
 await server.sessions.get('persisted').handle.dispose();record('stale',await call('wait',{sessionId:'persisted'}));await outsider.dispose();await server.shutdown();record('shutdown-resume',await call('resume',{sessionId:'new'}));record('shutdown-wait',await call('wait',{sessionId:'persisted'}))
 process.stdout.write(JSON.stringify(rows).split(JSON.stringify(workspace).slice(1,-1)).join('<work>'))
}finally{await server.shutdown();await ctx.fiber.dispose()}
