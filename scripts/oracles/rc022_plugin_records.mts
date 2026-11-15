import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts')
const {Session,default:Store,appendPluginRecord,pluginRecordOf}=await load('packages/core/session/src/index.ts')
const names=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const name of names){
 const session=Session.create('grammar'),result:any={name}
 try{result.returned=appendPluginRecord(session,name,{value:1});const event=session.eventAt(0),record=pluginRecordOf(event);Object.assign(result,{record:record!==undefined,identical:record.data===event.data,nodes:[...session.surface.nodes]})}
 catch(error:any){result.error=error.message}
 result.seq=session.seq;rows.push(result)
}
const session=Session.create('source');session.append('user/message',{id:'user',role:'user',source:{kind:'user'},content:[{type:'text',text:'hello'}]},{surfaceOp:'append'})
const data={count:1,nested:['a',2]},returned=appendPluginRecord(session,'plugin:test/state',data);data.nested.push('changed');data.count=2
const events=session.snapshotEvents(),record=pluginRecordOf(events[1]),resumed=Session.create('resume',events)
const restored=Session.fromRestore(session.id,events,session.header,0,'shared-frozen')
const child=Session.create('child',events,{...session.header,id:'child',parentSession:session.id,isSeeded:true},events.length)
rows.push({name:'durable',returned,data:record.data,identical:record.data===events[1].data,copies:[resumed,restored,child].map(item=>pluginRecordOf(item.snapshotEvents()[1]).data),
 messages:[session,resumed,restored,child].map(item=>item.deriveMessages()[0].content),nodes:[...session.surface.nodes],notRecord:[['turn/start',true],['plugin:a',false],['plugin:a',1],['plugin:',true]].map(([type,ignorable])=>pluginRecordOf({type,seq:0,time:0,data:{},ignorable})===undefined)})
for(const [name,data] of [['nan',NaN],['infinity',Infinity],['negative-zero',-0],['undefined',undefined]]){
 const current=Session.create('lossy');let error='accepted';try{appendPluginRecord(current,'plugin:test/number',data)}catch(caught:any){error=caught.message}rows.push({name,error,seq:current.seq})
}
for(const action of ['normal','failed','veto','reentry','detach']){
 const ctx=new Context(),result:any={name:'ownership-'+action,stages:[],heard:[],reentry:[]}
 try{
  await ctx.plugin(Store);const store=ctx.sessions,session=store.prepare('owned')
  const attempt=()=>{try{return appendPluginRecord(session,'plugin:test/state',{})}catch(error:any){return error.message}}
  result.stages.push(attempt());const detach=store.enter(session);result.stages.push(attempt())
  const stopCreated=ctx.on('session/created',()=>{result.stages.push(attempt());if(action==='failed')throw new Error('creation observer failed')})
  try{store.announce(session)}catch(error:any){result.announcement=error.message}
  ctx.on('session/event',(current:any,event:any)=>{result.heard.push({type:event.type,seq:event.seq,size:current.seq,record:pluginRecordOf(event)!==undefined});if(action==='reentry')result.reentry.push(attempt());if(action==='detach')detach()})
  ctx.on('internal/dispatch',(mode:any,name:any)=>{if(action==='veto'&&name==='session/event')throw new Error('record dispatch veto')})
  result.stages.push(attempt());detach();result.stages.push(attempt());Object.assign(result,{seq:session.seq,live:store.get(session.id)===session})
  stopCreated();const replacement=store.create('owned');result.stale=attempt();result.replacement=replacement.seq;rows.push(result)
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
