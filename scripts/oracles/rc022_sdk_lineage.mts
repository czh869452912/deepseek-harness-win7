import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=readFileSync(process.argv[3]!,'utf8'),{ctx,service,signal}=await setup(join(workspace,'source')),{HarnessSdkJsonRpcServer}=await load('packages/sdk/server/src/server.ts'),notes:any[]=[],rows:any[]=[],server=new HarnessSdkJsonRpcServer(ctx,{notify(method:any,params:any){notes.push({method,params})}})
const start=async(parent:any,id:string)=>{const receipt=await service.startActivation({provider:'spawn',parent,childId:id,name:id,label:'Task',prompt:[{type:'text',text:'task'}],signal,delivery:'caller'});while(ctx.agents.get(id).status!=='running')await new Promise(r=>setTimeout(r,1));return [receipt,ctx.agents.get(id)]}
try{
 await server.initialize({cwd:workspace,provider:'script',model:'model'})
 const parent=(await (server as any).getOrCreateSession('root')).handle.agent
 const [outer,child]=await start(parent,'child'),[inner]=await start(child,'grandchild')
 await inner.dispose();await inner.result;await outer.dispose();await outer.result;await new Promise(r=>setImmediate(r))
 rows.push({name:'actual-nested',notifications:notes.filter(note=>note.method.startsWith('subagent.')),live:['root','child','grandchild'].map(id=>ctx.agents.get(id)!==undefined)})
 notes.length=0
 for(const origin of ['user','fork','subagent'])ctx.emit('session/created',{id:origin,header:{origin,parentSession:'creator'}})
 rows.push({name:'origin-filter',notifications:[...notes]});notes.length=0
 const output=[{type:'text',text:'retained'}]
 ctx.emit('subagent/end',{local:false,provider:'remote',id:'same-id',parentSessionId:'unrelated',stopReason:'completed'})
 ctx.emit('subagent/end',{local:true,provider:'removed-provider',id:'retired',parentSessionId:'direct-parent',stopReason:'max-tokens',lastAssistantMessage:output})
 output.push({type:'text',text:'later mutation'})
 rows.push({name:'payload-owned',notifications:[...notes]})
 console.log(JSON.stringify(rows))
}finally{await server.shutdown();await ctx.fiber.dispose()}
