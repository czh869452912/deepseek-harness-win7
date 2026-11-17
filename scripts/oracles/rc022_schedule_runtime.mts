import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {ScheduleRuntime,MAX_TIMER_DELAY_MS}=await load('packages/schedule/schedule/src/runtime.ts')
const {scheduleTaskSchema}=await load('packages/schedule/schedule/src/storage.ts')
const {RemoteError}=await load('packages/typert/protocol/src/remote-error.ts')
const cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
const NativeDate=Date,realSetTimeout=globalThis.setTimeout,realClearTimeout=globalThis.clearTimeout,NOW=NativeDate.parse('2026-09-16T00:00:00Z')
function normalize(value:any){
 const sessions=new Map(),messages=new Map()
 const visit=(value:any):any=>{
  if(typeof value==='string'){
   if(/^session-[0-9a-f-]{36}$/.test(value)){if(!sessions.has(value))sessions.set(value,'reserved-'+(sessions.size+1));return sessions.get(value)}
   if(/^[0-9a-f-]{36}$/.test(value)){if(!messages.has(value))messages.set(value,'message-'+(messages.size+1));return messages.get(value)}
   return value
  }
  if(Array.isArray(value))return value.map(visit)
  if(value!==null&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,value])=>[key,visit(value)]))
  return value
 }
 return visit(JSON.parse(JSON.stringify(value)))
}
try{for(const name of cases){
 let clock=NOW,flushes=0;const trace:any[]=[],warnings:any[]=[],changed:any[]=[],agents=new Map<string,any>(),titles=new Map(),allAgents:any[]=[];let tasks:any[]=[]
 const iso=(epoch:number)=>new NativeDate(epoch).toISOString()
 globalThis.Date=class extends NativeDate{constructor(value?:any){super(value===undefined?clock:value)}static now(){return clock}} as any
 globalThis.setTimeout=((callback:any,delay:number)=>({delay,cancelled:false,unref(){}})) as any
 globalThis.clearTimeout=((handle:any)=>{if(handle)handle.cancelled=true}) as any
 class Agent{
  id:string;session:any;status='idle';inbox:any;idle:Promise<void>;finish!:()=>void
  constructor(id:string){this.id=id;this.session={id};this.inbox={nextTurn:[],nextStep:[],remove:(id:any)=>{this.inbox.nextTurn=this.inbox.nextTurn.filter((message:any)=>message.id!==id)}};this.idle=new Promise(resolve=>this.finish=resolve);allAgents.push(this)}
  followup(message:any){trace.push(['followup',this.id,message]);this.inbox.nextTurn.push(message);this.status='running'}
  whenIdle(){return this.idle}
 }
 agents.set('s',new Agent('s'))
 const activate=async(id:string)=>{
  trace.push(['activate',id]);if(name==='activateReject')throw new Error('activation refused')
  if(name==='rollbackActivate')clock=NOW-60000
  if(!agents.has(id))throw new RemoteError('session/not-found','not found',{})
  return agents.get(id)
 }
 const create=async(request:any)=>{trace.push(['create',request]);if(name==='newCreateReject')throw new Error('creation refused');agents.set(request.sessionId,new Agent(request.sessionId))}
 const flush=async(session:any)=>{trace.push(['flush',session.id]);flushes++;if(name==='rollbackFlush')clock=NOW-120000;if(name==='flushReject')throw new Error('flush refused');return !(name==='flushFalse'||name==='newRetry'&&flushes===1)}
 const services:any={agents:{withoutInitiator:(operation:any)=>operation()},sessions:{flush},sessionController:{create},sessionTitle:{get:(session:any)=>titles.get(session.id),rename:(session:any,title:any)=>{titles.set(session.id,title);trace.push(['title',session.id,title])}},workspaceRegistry:{archivedSessionIds:['manualArchived','recoveryArchived'].includes(name)?['s']:name==='newArchived'?['reserved']:[]}}
 const ctx:any={...services,logger:{warn:(message:any)=>warnings.push(message)},get:(key:string)=>services[key],waterfall:(event:any,id:any,next:any)=>next()}
 const record:any={id:'a',kind:['every','batch','partialCommit','floorOccurrence','floorAck','newFloor'].includes(name)?'every':'after',title:'Title',prompt:'prompt',scheduledAt:iso(NOW-60000)}
 record[record.kind==='every'?'everySeconds':'afterSeconds']=60
 if(['future','farFuture'].includes(name))record.scheduledAt=iso(NOW+(name==='future'?60000:MAX_TIMER_DELAY_MS+60000))
 const target=['newOnce','newArchived'].includes(name)?{kind:'new_once',sessionId:'reserved',create:{}}:['newEach','newRetry','newCreateReject','newFloor'].includes(name)?{kind:'new',create:{}}:{kind:'session',sessionId:'s'}
 const raw:any={record,target,deliveryHistory:{records:[],earlierRecordsUnavailable:false},status:name==='manualPaused'?'paused':'active'}
 if(name.startsWith('recovery')||['floorOccurrence','floorAck','newFloor'].includes(name)){
  const ack={targetSessionId:'s',scheduledAt:iso(NOW-(['floorAck','newFloor'].includes(name)?60000:120000)),deliveredAt:iso(NOW-1000),messageId:'message-0'}
  Object.assign(raw,{lastDelivery:ack,updatedAt:iso(NOW+60000),deliveryHistory:{records:[ack],earlierRecordsUnavailable:true}})
  if(name.startsWith('recovery')){agents.get('s').inbox.nextTurn=[{id:ack.messageId,role:'user',content:[{type:'text',text:'saved'}],source:{kind:'schedule'}}];if(name==='recoveryRunning')agents.get('s').status='running'}
 }
 tasks.push(scheduleTaskSchema.parse(raw))
 if(['batch','partialCommit'].includes(name))tasks.push(scheduleTaskSchema.parse({...raw,record:{...record,id:'b',prompt:'second'}}))
 const commit=async(task:any)=>{trace.push(['commit',task]);if(name==='partialCommit'&&task.record.id==='b')throw new Error('write refused');tasks[tasks.findIndex(current=>current.record.id===task.record.id)]=task}
 const runtime:any=new ScheduleRuntime(ctx,()=>tasks,(operation:any)=>operation(),commit,()=>changed.push(true),{retention:{days:30,records:200},newSessionIntervalMs:3600000},activate)
 let result:any=null,outcome
 try{
  if(name.startsWith('manual')){result=await runtime.runNow(name==='manualMissing'?'missing':'a');if(['manual','manualPaused'].includes(name))result=[result,await runtime.runNow('a')]}
  else{await runtime.drive();if(name==='newRetry')await runtime.drive()}
  outcome={value:result??null}
 }catch(error:any){outcome={error:{code:error.code??null,message:error.message}}}
 const row=normalize({case:name,outcome,tasks,trace,executing:[...runtime.executing].sort(),warnings:warnings.length,changed:changed.length,timer:runtime.timer?.delay??null})
 await runtime.dispose();for(const agent of allAgents)agent.finish();await Promise.resolve();await Promise.resolve();rows.push(row)
}}finally{globalThis.Date=NativeDate;globalThis.setTimeout=realSetTimeout;globalThis.clearTimeout=realClearTimeout}
console.log(JSON.stringify(rows))
