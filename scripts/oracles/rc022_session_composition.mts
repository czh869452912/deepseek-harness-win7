import {readFileSync,mkdirSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),directory=join(workspace,'source-work');mkdirSync(directory)
const fixture=await setup(join(workspace,'source'),directory),ctx=fixture.ctx,rows:any[]=[],events:any[]=[],resolvers:any[]=[],streams:any[]=[]
const {default:Controller}=await load('packages/api/session-controller/src/index.ts'),{Peer}=await load('packages/client/connection/src/peer.ts')
let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(resolve=>release=resolve),ready=new Promise<void>(resolve=>entered=resolve);let mounting:Promise<any>|undefined
try{
 for(const path of ['packages/typert/registry/src/index.ts','packages/api/remote-access/src/index.ts','packages/api/gateway/src/index.ts'])await ctx.plugin((await load(path)).default)
 ctx.provide('agentDefaultModel',{currentSelection:()=>({provider:'script',model:'model'})})
 ctx.provide('attachments',{imageLimits:{maxImageBytes:1,maxImagesPerMessage:1,maxMessageImageBytes:1,maxImagePixels:1,maxImageDimension:1,mediaTypes:['image/png']}})
 ctx.provide('fileUploads',{registerAgentResolver:(callback:any)=>{resolvers.push(callback);return()=>resolvers.splice(resolvers.indexOf(callback),1)}})
 const archived:string[]=[];ctx.provide('workspaceRegistry',{archivedSessionIds:archived,list:()=>[]})
 ctx.on('api-session/added',(value:any)=>events.push({type:'added',sessionId:value.sessionId,agentAvailable:value.agentAvailable}));ctx.on('api-session/removed',(sessionId:string)=>events.push({type:'removed',sessionId}))
 const handle=await ctx.agents.create({sessionId:'boot',meta:{cwd:directory},agentOptions:{provider:'script',model:'model'}}),agent=handle.agent,original=ctx.sessionProjections.register.bind(ctx.sessionProjections);let first=true
 ctx.sessionProjections.register=async(...args:any[])=>{if(first){first=false;entered();await gate}return original(...args)}
 mounting=(async()=>await ctx.plugin(Controller,{nativeOpen:false,listWorkSliceMs:4}))();await ready
 ctx.emit('agent/assistant-stream',{agent,frame:{type:'start',attemptId:'boot-attempt',revision:1,turn:1,step:1}})
 release();const provider=await mounting;ctx.sessionProjections.register=original;const api=ctx.sessionController
 const opening=api.follow({address:{kind:'session',sessionId:'boot'},assistantStream:true},fixture.signal)[Symbol.asyncIterator]();streams.push(opening);const value=(await opening.next()).value
 rows.push({name:'opening-captured-during-init',baseline:value.assistantStream,resolvers:resolvers.length,budget:(api as any).listState.workSliceMs,hasLegacyHistory:'history'in api});await opening.return?.()
 const owner=new Peer(ctx,{principal:{kind:'owner'}}),invoke=(method:string,request:any)=>ctx.typertGateway.invoke({namespace:'session',method,args:{request},peer:owner,signal:fixture.signal})
 rows.push({name:'state-through-gateway',value:await invoke('state',{sessionId:'boot'})},{name:'wait-through-gateway',reason:(await invoke('wait',{sessionId:'boot'})).reason},{name:'upload-resolver',same:await resolvers[0]('boot')===agent})
 const created=await ctx.agents.create({sessionId:'availability',meta:{cwd:directory},agentOptions:{provider:'script',model:'model'}});await created.dispose();rows.push({name:'availability-events',value:[...events]});events.length=0
 const control=api.control(fixture.signal)[Symbol.asyncIterator]();streams.push(control);const baseline=(await control.next()).value;rows.push({name:'projection-control',type:baseline.type,keys:Object.keys(baseline.value).sort(),sessions:Object.keys(baseline.value.projections).sort()});await control.return?.()
 archived.push('boot');agent.followup({id:'blocked',role:'user',content:[{type:'text',text:'blocked'}],source:{kind:'user'}});await agent.whenIdle();const records=agent.session.snapshotEvents()
 rows.push({name:'archive-stops-model-step',requests:records.filter((event:any)=>event.type==='request/header').length,ending:records.filter((event:any)=>event.type==='turn/end').map((event:any)=>event.data.reason.kind)})
 await provider.dispose();const before=events.length;ctx.sessions.create('after-unload',{meta:{cwd:directory}})
 rows.push({name:'unloaded',resolvers:resolvers.length,newEvents:events.length-before,baselines:(api as any).historyController.streamsListener.streams.size,serviceGone:ctx.get('sessionController')===undefined})
}finally{release();await mounting?.catch(()=>{});for(const stream of streams)await stream.return?.();await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
