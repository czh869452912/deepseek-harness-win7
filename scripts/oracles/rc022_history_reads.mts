import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {createRequire} from 'node:module'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),fixture=await setup(join(workspace,'source')),ctx=fixture.ctx,rows:any[]=[],observed:string[]=[]
const {HistoryController}=await load('packages/api/session-controller/src/history/controller.ts'),Cache=await load('packages/session/session-projection-cache/src/index.ts'),{z}=createRequire(join(process.argv[2]!,'packages/session/session-projection/package.json'))('zod')
const query=ctx.sessionQuery.observeSession.bind(ctx.sessionQuery)
ctx.sessionQuery.observeSession=async(id:any,options:any)=>{observed.push(options.projectionMode);return query(id,options)}
try{
 await ctx.plugin((await load('packages/storage/storage/src/index.ts')).default)
 await ctx.plugin(await load('packages/storage/storage-json/src/index.ts'),{root:join(workspace,'source-storage')})
 await ctx.plugin(await load('packages/storage/storage-domain/src/index.ts'),{backend:'json'})
 await ctx.sessionProjections.register({key:'title',stateVersion:1,stateSchema:z.string(),init:()=> 'Title',apply:(state:any)=>state,wire:{viewSchema:z.string(),view:(state:any)=>state}})
 await ctx.plugin(Cache.default,{writeEveryEvents:1000,writeIntervalMs:60000})
 const history=new HistoryController(ctx),handle=await ctx.agents.create({sessionId:'history',meta:{cwd:'C:/history'},agentOptions:{provider:'script',model:'model'}}),session=handle.agent.session
 for(const turn of [1,2,3]){
  session.append('turn/start',{turn})
  session.append('user/message',{id:'u'+turn,role:'user',content:[{type:'text',text:'prompt'}],source:{kind:'user'}},{surfaceOp:'append'})
  session.append('step/start',{turn,step:1})
  session.append('assistant/message',{turn,step:1,message:{id:'a'+turn,role:'assistant',content:[{type:'text',text:'answer'}],source:{kind:'model',provider:'script',model:'model'}},stream:[]},{surfaceOp:'append'})
  session.append('step/end',{turn,step:1})
  session.append('turn/end',{turn,reason:{kind:'completed'}})
 }
 const address={kind:'session',sessionId:'history'},read=async(name:string,request:any)=>rows.push({name,value:await history.events({address,...request},fixture.signal)})
 await read('default-cut',{});await read('fixed-cut',{throughSeq:11,maxMessages:2});await read('older-page',{beforeSeq:12,maxMessages:1});await read('empty-cut',{throughSeq:-1});await read('turn-window',{maxMessages:6,turnWindow:{minMessages:2,minTurns:2}})
 rows.push({name:'assistant-output',value:await history.assistantOutput('history',3,17,1,fixture.signal)},{name:'assistant-interval',value:await history.assistantOutput('history',9,17,2,fixture.signal)})
 for(const [name,request] of [['future-cut',{throughSeq:100}],['negative-zero',{throughSeq:-0}],['bad-window',{maxMessages:1,turnWindow:{minMessages:2,minTurns:1}}]] as const){try{await history.events({address,...request},fixture.signal)}catch(error:any){rows.push({name,error:{code:error.code,message:error.message}})}}
 rows.push({name:'live-projections',value:await history.projections({sessionId:'history'},fixture.signal)})
 await ctx.sessionProjectionCache.write(session);rows.push({name:'header-cache',value:ctx.sessionProjectionCache.cachedSnapshot(session.header,['title'])})
 await handle.dispose();const before=observed.length
 rows.push({name:'cold-projections',value:await history.projections({sessionId:'history'},fixture.signal),reads:observed.length-before,agentAbsent:ctx.agents.get('history')===undefined})
 await read('cold-history',{maxMessages:2});rows.push({name:'missing-projections',value:await history.projections({sessionId:'missing'},fixture.signal)})
 try{await history.events({address:{kind:'subagent',parentSessionId:'parent',childSessionId:'missing',mode:'unknown'}},fixture.signal)}catch(error:any){rows.push({name:'missing-subagent',error:{code:error.code,details:error.details}})}
 const cache=ctx.sessionProjectionCache,table=cache.table,header={version:4,id:'seeded-cache',createdAt:10,cwd:'C:/cache',isSeeded:true},row={identity:{formatVersion:4,createdAt:10,cwd:'C:/cache',isSeeded:true,inheritedEventCount:7},rows:{title:{ver:1,seq:9,val:'Seeded title'}}}
 await table.put(header.id,row)
 rows.push({name:'seeded-header-cache',value:cache.cachedSnapshot(header),wrongCutSeeds:cache.recordFor(header.id,{...row.identity,inheritedEventCount:0})!==undefined})
 rows.push({name:'cache-lifecycle-refusal',value:cache.cachedSnapshot({...header,createdAt:11})??null})
 await table.put(header.id,{...row,identity:{...row.identity,formatVersion:3}})
 rows.push({name:'predecessor-title',current:cache.cachedSnapshot(header)??null,predecessor:cache.cachedPredecessorTitle(header)})
 const persistence=ctx.sessionPersistence,stat=persistence.stat;persistence.stat=async()=>({header,formatStatus:'migration-required'})
 await table.put(header.id,row);const beforeMigration=observed.length
 rows.push({name:'migration-hints',value:await history.projections({sessionId:header.id},fixture.signal),reads:observed.length-beforeMigration})
 persistence.stat=stat
 const abort=new AbortController();abort.abort()
 try{await history.projections({sessionId:'history'},abort.signal)}catch(error:any){rows.push({name:'projection-aborted',error:{code:error.code,message:error.message}})}
 rows.push({name:'passive',agents:ctx.agents.list().length,modes:observed})
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows,(_key,value)=>value&&typeof value==='object'&&'type'in value&&'seq'in value&&'time'in value?{...value,time:0}:value))
