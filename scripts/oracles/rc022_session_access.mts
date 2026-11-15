import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const Registry=(await load('packages/typert/registry/src/index.ts')).default,Access=(await load('packages/api/remote-access/src/index.ts')).default,Gateway=(await load('packages/api/gateway/src/index.ts')).default,Controller=(await load('packages/api/session-controller/src/index.ts')).default,{SessionControlController}=await load('packages/api/session-controller/src/control.ts'),{Peer}=await load('packages/client/connection/src/peer.ts'),{z}=await load('node_modules/zod/index.js')
const fixture=await setup(join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source')),{ctx}=fixture,rows:any[]=[],streams:any[]=[]
const project=(frame:any)=>frame.type==='baseline'?{type:'baseline',keys:Object.keys(frame.value.projections).sort(),values:Object.fromEntries(Object.entries(frame.value.projections).map(([key,value]:any)=>[key,value.values.accessProbe]))}:{type:frame.type,sessionId:frame.sessionId,seq:frame.seq,changes:frame.changes.filter((change:any)=>change.key==='accessProbe')}
try{
 await ctx.plugin(Registry);await ctx.plugin(Access);await ctx.plugin(Gateway)
 await ctx.sessionProjections.register({key:'accessProbe',stateVersion:1,stateSchema:z.number(),init:()=>0,apply:(state:any,event:any)=>event.type==='access/probe'?event.data.value:state,wire:{viewSchema:z.number(),view:(state:any)=>state}})
 const agents=[];for(const sessionId of ['shared','hidden'])agents.push((await ctx.agents.create({sessionId,agentOptions:{provider:'script',model:'model'}})).agent)
 const api=new Controller(ctx,{}),calls:string[]=[],items=[{sessionId:'hidden',title:'Hidden'},{sessionId:'shared',title:'Shared'}]
 api.listState={list:async()=>{calls.push('list');return items},search:async()=>{calls.push('search');return {items:items.map(item=>({sessionId:item.sessionId,snippet:item.title})),hasMore:true}}};api.controlState=new SessionControlController(ctx)
 let held=['shared'],globalAccess=true
 ctx.remoteAccess.registerPolicy('guest',{bindings(){const actions=['session/list','session/search','session/control'];return [...globalAccess?[{resource:{kind:'global'},role:{actions}}]:[],...held.map(id=>({resource:{kind:'session',id},role:{actions}}))]}})
 const owner=new Peer(ctx,{principal:{kind:'owner'}}),guest=new Peer(ctx,{principal:{kind:'guest',id:'g'}})
 const call=(peer:any,method:string,args:any)=>ctx.typertGateway.invoke({namespace:'session',method,args,peer,signal:fixture.signal})
 for(const [label,peer]of [['owner',owner],['guest',guest]]){rows.push({name:label+'-list',value:await call(peer,'list',{_request:{}})});rows.push({name:label+'-search',value:await call(peer,'search',{request:{query:'hit'}})})}
 globalAccess=false;const before=calls.length;try{await call(guest,'list',{_request:{}})}catch(error:any){rows.push({name:'global-refusal',code:error.code,reads:calls.length-before})}globalAccess=true
 const signals=[new AbortController(),new AbortController()]
 for(const [label,peer,controller]of [['owner',owner,signals[0]],['guest',guest,signals[1]]]as any){const stream=(await ctx.typertGateway.stream({namespace:'session',method:'control',args:{},peer,signal:controller.signal}))[Symbol.asyncIterator]();streams.push(stream);rows.push({name:label+'-baseline',value:project((await stream.next()).value)})}
 agents[1].session.append('access/probe',{value:1});agents[0].session.append('access/probe',{value:2});rows.push({name:'owner-updates',value:[project((await streams[0].next()).value),project((await streams[0].next()).value)]});rows.push({name:'guest-update',value:project((await streams[1].next()).value)})
 held=['hidden'];agents[0].session.append('access/probe',{value:3});agents[1].session.append('access/probe',{value:4});rows.push({name:'changed-grant',value:project((await streams[1].next()).value)})
 for(const controller of signals)controller.abort();const ended=[];for(const stream of streams){try{ended.push((await stream.next()).done)}catch(error:any){ended.push({error:error.code})}};rows.push({name:'cancelled',ended,subscriptions:api.controlState.streams.size,inputs:items})
}finally{for(const stream of streams)await stream.return?.();await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
