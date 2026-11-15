import {join} from 'node:path'
import {readFileSync} from 'node:fs'
import {load,setup} from './rc022_subagent_fixture.mts'
const {default:Team}=await load('packages/team/agent-team/src/index.ts'),workspace=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source'),rows:any[]=[]
const failure=(error:any)=>({error:error.code??null,message:error.message??String(error)})
for(const input of JSON.parse(readFileSync(process.argv[4]!,'utf8'))){
 const fixture=await setup(join(workspace,input.name)),{ctx,signal}=fixture,row:any={name:input.name,results:[]},originalFlush=ctx.sessions.flush
 let owner:any
 try{
  owner=await ctx.plugin(Team,input.config??{});let team=ctx.agentTeams
  const parent=await ctx.agentLoop.create('root',{provider:'script',model:'model'})
  ctx.on('agent/pre-step',async({agent}:any,next:any)=>agent===parent?{kind:'reject'}:next())
  const actors:any={root:parent},receipts:any={}
  for(const id of ['a','b']){receipts[id]=await fixture.service.startActivation({provider:'spawn',parent,childId:id,name:id,label:'Task',prompt:[{type:'text',text:'TASK:'+id}],signal,delivery:'caller'});actors[id]=ctx.agents.get(id)}
  let flushMode='real'
  const flush=async function(session:any){if(flushMode==='false')return false;if(flushMode==='error')throw Error('disk unavailable');return originalFlush.call(ctx.sessions,session)}
  ctx.sessions.flush=flush
  const execute=async(command:any):Promise<any>=>{
   try{
    const caller=actors[command.caller??'root'],{op,caller:_caller,...request}=command
    if(op==='enable'){await team.setEnabled(caller,command.value,signal);return {enabled:team.isEnabled(parent)}}
    if(op==='create')return await team.createTask(caller,request,signal)
    if(op==='update')return await team.updateTask(caller,request,signal)
    if(op==='get')return team.getTask(caller,command.taskId)
    if(op==='cold'){await receipts[command.identity].dispose();return {cold:command.identity}}
    if(op==='flush'){flushMode=command.value;return {flush:flushMode}}
    if(op==='concurrent')return await Promise.all(command.requests.map(execute))
    if(op==='reload'){await owner.dispose();owner=await ctx.plugin(Team,input.config??{});team=ctx.agentTeams;return {reloaded:true}}
    if(op==='queue-race'){
     const entered=Promise.withResolvers<void>(),release=Promise.withResolvers<void>();let released=false
     ctx.sessions.flush=async function(session:any){if(session===parent.session&&!released){entered.resolve();await release.promise}return originalFlush.call(this,session)}
     const first=execute({op:'create',subject:'first',description:'first'});await entered.promise
     const second=execute({op:'create',subject:'second',description:'second',caller:'a'});let mode:any
     if(command.race==='stale')await receipts.a.dispose()
     else mode=execute({op:'enable',value:false})
     released=true;release.resolve();const results=await Promise.all([first,second]);if(mode)await mode
     ctx.sessions.flush=flush;return results
    }
    throw Error('unknown probe operation')
   }catch(error){return failure(error)}
  }
  for(const command of input.commands)row.results.push(await execute(command))
  row.projection=ctx.sessionProjections.snapshot(parent.session).values.agentTeam
  row.taskEvents=parent.session.snapshotEvents().filter((e:any)=>e.type==='team/task').length
  row.modeEvents=parent.session.snapshotEvents().filter((e:any)=>e.type==='team/mode').length
  row.tails=team['journal']['tails'].size
 }catch(error){Object.assign(row,failure(error))}
 finally{ctx.sessions.flush=originalFlush;if(owner!==undefined)await owner.dispose();row.released=ctx.get('agentTeams')===undefined;await ctx.fiber.dispose()}
 rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
