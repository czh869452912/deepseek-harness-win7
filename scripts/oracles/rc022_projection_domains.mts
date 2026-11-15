import {readFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {statsCase} from './session_stats_current_source.mts'
const source=process.argv[2]!,load=(path:string)=>import(pathToFileURL(resolve(source,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Store}=await load('packages/core/session/src/index.ts'),{default:Registry}=await load('packages/session/session-projection/src/index.ts')
const Stats=await load('packages/session/session-stats/src/index.ts'),Outline=await load('packages/session/session-turn-outline/src/index.ts')
function decode(value:any):any{if(Array.isArray(value))return value.map(decode);if(value&&typeof value==='object'){if(Object.keys(value).length===1&&'$scalar'in value)return ({undefined,'-0':-0,NaN,Infinity}as any)[value.$scalar];return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,decode(v)]))}return value}
const cases=JSON.parse(await readFile(new URL('./session_stats_current_cases.json',import.meta.url),'utf8')),rows:any[]=[]
for(const test of cases)rows.push({case:test.case,value:await statsCase(source,test,decode)})
for(const action of ['fresh','late','deferred-stats','deferred-outline']){
 const ctx=new Context();try{
  await ctx.plugin(Store);await ctx.plugin(Registry);const registry=ctx.sessionProjections,session=ctx.sessions.create('domains'),row:any={case:action}
  if(action.startsWith('deferred')){
   let enter:any,release:any;const entered=new Promise(resolve=>{enter=resolve}),gate=new Promise(resolve=>{release=resolve}),original=registry.register.bind(registry)
   registry.register=async(definition:any)=>{enter();await gate;return original(definition)}
   const fiber=ctx.plugin(action==='deferred-stats'?Stats:Outline);await entered;row.waiting=fiber.state;row.before=registry.snapshot(session);release();await fiber;row.ready=fiber.state;row.keys=Object.keys(registry.snapshot(session).values).sort();rows.push(row);continue
  }
  const mount=async()=>[await ctx.plugin(Stats),await ctx.plugin(Outline)];let fibers=action==='fresh'?await mount():undefined
  for(const [kind,data] of [['turn/start',{turn:1}],['step/start',{turn:1,step:1}],['step/end',{turn:1,step:1}],['turn/end',{turn:1}]])session.append(kind as any,data as any)
  fibers??=await mount();row.summary=registry.snapshot(session,registry.summaryKeys());row.full=registry.snapshot(session);const checkpoint=registry.checkpoint(session);row.cold=registry.restore(checkpoint,[],session.seq,session.header,session.inheritedEventCount).snapshot;row.checkpointKeys=Object.keys(checkpoint).sort();await fibers[0]!.dispose();await fibers[1]!.dispose();row.released=registry.snapshot(session);row.retainedKeys=Object.keys(registry.checkpoint(session)).sort();await mount();row.remounted=registry.snapshot(session);rows.push(row)
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
