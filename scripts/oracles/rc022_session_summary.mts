import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {createRequire} from 'node:module'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),fixture=await setup(join(workspace,'source')),ctx=fixture.ctx,rows:any[]=[],opens:any[]=[]
const {ApiSessionList}=await load('packages/api/session-controller/src/list.ts'),Cache=await load('packages/session/session-projection-cache/src/index.ts'),{z}=createRequire(join(process.argv[2]!,'packages/session/session-projection/package.json'))('zod')
const limits={maxImageBytes:1,maxImagesPerMessage:1,maxMessageImageBytes:1,maxImagePixels:1,maxImageDimension:1,mediaTypes:['image/png']}
ctx.provide('attachments',{imageLimits:limits})
try{
 await ctx.plugin((await load('packages/storage/storage/src/index.ts')).default);await ctx.plugin(await load('packages/storage/storage-json/src/index.ts'),{root:join(workspace,'source-storage')});await ctx.plugin(await load('packages/storage/storage-domain/src/index.ts'),{backend:'json'})
 const listing=new ApiSessionList(ctx,1);await listing.initialize()
 await ctx.sessionProjections.register({key:'title',stateVersion:1,stateSchema:z.string(),init:()=> 'Title',apply:(state:any)=>state,wire:{viewSchema:z.string(),view:(state:any)=>state}})
 await ctx.plugin(Cache.default,{writeEveryEvents:1000,writeIntervalMs:60000})
 const handle=await ctx.agents.create({sessionId:'summary',meta:{cwd:'C:/summary',createdAt:100},agentOptions:{provider:'script',model:'model'}}),session=handle.agent.session
 rows.push({name:'blank-live',value:listing.summaryFor(session)})
 session.append('user/message',{id:'prompt',role:'user',content:[{type:'text',text:'hello'}],source:{kind:'user'}},{surfaceOp:'append'})
 rows.push({name:'prompt-still-blank',value:listing.summaryFor(session),recency:listing.summaryFor(session).updatedAt===session.snapshotEvents().at(-1).time})
 session.append('turn/start',{turn:1});session.append('turn/end',{turn:1,reason:{kind:'completed'}})
 rows.push({name:'started-live',value:listing.summaryFor(session)},{name:'all-wire',value:ctx.sessionProjections.snapshot(session)})
 await ctx.sessionProjectionCache.write(session);await handle.dispose()
 const original=ctx.sessionPersistence.open.bind(ctx.sessionPersistence);ctx.sessionPersistence.open=(...args:any[])=>{opens.push(true);return original(...args)}
 rows.push({name:'cold-cached-list',value:await listing.list(fixture.signal),opens:opens.length,agents:ctx.agents.list().length})
 const header={version:4,id:'seeded',createdAt:10,cwd:'C:/seeded',isSeeded:true}
 await ctx.sessionProjectionCache.table.put('seeded',{identity:{formatVersion:4,createdAt:10,cwd:'C:/seeded',isSeeded:true,inheritedEventCount:7},rows:{title:{ver:1,seq:9,val:'Seeded'},sessionListMetadata:{ver:1,seq:7,val:{blank:true,lastPromptAt:null}},imageLimits:{ver:1,seq:10,val:null}}})
 rows.push({name:'seeded-header',value:(listing as any).summarizeCold({header,formatStatus:'current'})})
 rows.push({name:'cold-miss',value:(listing as any).summarizeCold({header:{version:4,id:'miss',createdAt:4,cwd:'C:/miss',isSeeded:false},formatStatus:'migration-required'})})
 const live=ctx.sessions.create('attached',{meta:{createdAt:3,cwd:'C:/attached'}});rows.push({name:'attached-no-agent',value:listing.summaryFor(live)})
 await ctx.sessionProjections.register({key:'broken',stateVersion:1,stateSchema:z.string(),init:()=> 'state',apply:(state:any)=>state,wire:{viewSchema:z.string(),view:()=>{throw Error('view failed')}}})
 rows.push({name:'wire-failure-keeps-metadata',value:listing.summaryFor(live)})
 const abort=new AbortController();abort.abort();try{await listing.list(abort.signal)}catch(error:any){rows.push({name:'cancelled',nameOfError:error.name})}
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows,(key,value)=>key==='updatedAt'||key==='lastPromptAt'&&value!==null?0:value))
