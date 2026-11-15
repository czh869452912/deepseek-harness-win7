import {readFileSync,mkdirSync} from 'node:fs'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {load,setup} from './rc022_subagent_fixture.mts'
const base=JSON.parse(readFileSync(process.argv[3]!,'utf8')),directory=join(base,'source-work'),moved=join(directory,'moved');mkdirSync(moved,{recursive:true})
const fixture=await setup(join(base,'source'),directory),ctx=fixture.ctx,rows:any[]=[],calls:any[]=[]
try{
 for(const path of ['packages/typert/registry/src/index.ts','packages/skill/skill/src/index.ts','vendor/loader/src/index.ts'])await ctx.plugin((await load(path)).default)
 ctx.baseUrl=pathToFileURL(base).href+'/'
 ctx.loader.builtins.contribute={name:'contribute',inject:['skills'],apply(child:any,config:any){child.skills.register({name:config.name,description:'Preset skill',source:'test',content:'instructions',path:'/virtual/SKILL.md',whenToUse:'Review',invocation:{modelInvocable:false,userInvocable:true}})}}
 await ctx.plugin((await load('packages/preset/agent-preset-registry/src/index.ts')).default,{default:'coding'});const presets=ctx.agentPresets,definition=(name:string)=>({id:'coding',plugins:[{id:'skills',name:'cordis:contribute',config:{name}}]})
 const unregister=await presets.register(definition('review'))
 ctx.skills.register({name:'global',description:'Global skill',source:'test',content:'instructions',invocation:{modelInvocable:true,userInvocable:true}});ctx.skills.register({name:'hidden',description:'Model only',source:'test',content:'instructions',invocation:{modelInvocable:true,userInvocable:false}})
 const {SessionSkillCatalog}=await load('packages/api/session-controller/src/skill-catalog.ts'),catalog=new SessionSkillCatalog(ctx),original=ctx.skills.list.bind(ctx.skills)
 const listing=async(options:any)=>{calls.push({cwd:options.cwd===moved?'moved':options.cwd===directory?'default':options.cwd,scope:options.scope?.session?'live':options.scope?'standing':'global'});return original(options)};ctx.skills.list=listing
 const session=ctx.sessions.create('cold',{meta:{cwd:directory,agentPreset:'coding'}});session.append('working-directory/change',{cwd:moved})
 rows.push({name:'cold-projected',value:await catalog.list({sessionId:'cold'},fixture.signal),call:calls.at(-1),agents:ctx.agents.list().length})
 ctx.sessions.create('default');const aborted=new AbortController();aborted.abort()
 rows.push({name:'cold-default-admitted-cancel',value:await catalog.list({sessionId:'default'},aborted.signal),call:calls.at(-1)})
 ctx.sessions.create('unknown',{meta:{cwd:'/offline',agentPreset:'absent'}});rows.push({name:'unknown-preset-offline',value:await catalog.list({sessionId:'unknown'},fixture.signal),call:calls.at(-1)})
 const handle=await ctx.agents.create({sessionId:'live',meta:{cwd:directory},agentOptions:{provider:'script',model:'model'},setup:async(child:any)=>{await presets.mount(child,'coding')}})
 await ctx.workingDirectory.set(handle.agent,moved,fixture.signal);rows.push({name:'live-directory',value:await catalog.list({sessionId:'live'},fixture.signal),call:calls.at(-1)});await handle.dispose()
 rows.push({name:'persisted-directory',value:await catalog.list({sessionId:'live'},fixture.signal),call:calls.at(-1),agents:ctx.agents.list().length})
 let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(resolve=>release=resolve),started=new Promise<void>(resolve=>entered=resolve)
 ctx.skills.list=async(options:any)=>{entered();await gate;return listing(options)}
 const pending=catalog.list({sessionId:'cold'},fixture.signal);await started;await unregister();const replacement=await presets.register(definition('review-new'))
 rows.push({name:'retained-during-read',generations:presets.inspectCompositions().map((row:any)=>row.id)});release();rows.push({name:'retired-view',value:await pending});rows.push({name:'released-after-read',generations:presets.inspectCompositions().map((row:any)=>row.id)})
 ctx.skills.list=listing;rows.push({name:'replacement-view',value:await catalog.list({sessionId:'cold'},fixture.signal)})
 ctx.skills.list=async()=>{throw Error('catalog failed')};try{await catalog.list({sessionId:'cold'},fixture.signal)}catch(error:any){rows.push({name:'listing-error',code:error.code,message:error.message})}
 await replacement();rows.push({name:'released-after-error',generations:presets.inspectCompositions().map((row:any)=>row.id)})
 try{await catalog.list({sessionId:'missing'},fixture.signal)}catch(error:any){rows.push({name:'missing',code:error.code,details:error.details})}
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
