import {readFileSync} from 'node:fs'
import {mkdir,rmdir} from 'node:fs/promises'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),{ctx}=await setup(join(workspace,'sessions-source'),workspace),{HarnessSdkJsonRpcServer}=await load('packages/sdk/server/src/server.ts'),server=new HarnessSdkJsonRpcServer(ctx,{notify(){}}),rows:any[]=[]
async function call(method:string,params:any){try{return {value:await server.handleRequest('session/working-directory/'+method,params)}}catch(error:any){return {error:error.message,name:error.name}}}
function record(name:string,result:any){rows.push({name,result,agents:ctx.agents.list().map((agent:any)=>agent.id)})}
try{
 record('before-get',await call('get',{sessionId:'a'}));record('before-set',await call('set',{sessionId:'a',path:'child'}))
 await server.initialize({cwd:workspace,provider:'script',model:'model'})
 for(const [name,method,params] of [['bad-id-empty','get',{sessionId:''}],['bad-id','get',{}],['bad-id-type','get',{sessionId:3}],['bad-path','set',{sessionId:'a',path:3}]] as const)record(name,await call(method,params))
 record('initial',await call('get',{sessionId:'a',extra:'ignored'}));record('relative',await call('set',{sessionId:'a',path:'child'}));record('isolation',await call('get',{sessionId:'b'}))
 await rmdir(join(workspace,'child'));record('recovered',await call('get',{sessionId:'a'}));await mkdir(join(workspace,'child'))
 record('absolute',await call('set',{sessionId:'a',path:join(workspace,'child')}));record('missing',await call('set',{sessionId:'a',path:'missing'}))
 const agent=ctx.agents.get('a');rows.push({name:'durable',origin:agent.session.header.cwd,current:ctx.workingDirectory.get(agent.session),changes:agent.session.snapshotEvents().filter((event:any)=>event.type==='working-directory/change').map((event:any)=>event.data)})
 await server.sessions.get('a').handle.dispose();record('stale',await call('get',{sessionId:'a'}));record('concurrent',{value:await Promise.all([call('get',{sessionId:'c'}),call('get',{sessionId:'c'})])})
 await server.shutdown();record('shutdown',await call('get',{sessionId:'new'}))
 process.stdout.write(JSON.stringify(rows).split(JSON.stringify(workspace).slice(1,-1)).join('<work>'))
}finally{await server.shutdown();await ctx.fiber.dispose()}
