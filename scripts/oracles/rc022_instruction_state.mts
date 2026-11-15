import {readFileSync,mkdirSync,writeFileSync,unlinkSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const base=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source'),project=join(base,'project'),home=join(base,'home'),shared=join(base,'shared'),nested=join(project,'pkg')
for(const path of [project,home,shared,nested])mkdirSync(path,{recursive:true})
const write=(path:string,text:string)=>writeFileSync(path,text)
write(join(project,'.git'),'marker');write(join(home,'AGENTS.md'),'global');write(join(shared,'AGENTS.md'),' global ')
write(join(project,'AGENTS.md'),'first');write(join(project,'CLAUDE.md'),'second');write(join(nested,'AGENTS.md'),'nested')
const fixture=await setup(join(base,'sessions'),project),{ctx}=fixture,state=await load('packages/context/agent-instructions/src/state.ts'),config=await load('packages/context/agent-instructions/src/config.ts'),{createUserMessage}=await load('packages/llm/llm/src/index.ts'),rows:any[]=[]
let handle:any
const message=(text:string,changes:any[]=[])=>createUserMessage({content:[{type:'text',text}],source:{kind:'agent-instructions',form:'instructions',changes}})
try{
 handle=await ctx.agents.create({sessionId:'instructions',meta:{cwd:project},agentOptions:{provider:'script',model:'model'}})
 const agent=handle.agent,filesystem=ctx.fs,cache=new WeakMap(),reads:any[]=[],fail=new Set(),originalStream=filesystem.streamText.bind(filesystem),originalStat=filesystem.stat.bind(filesystem)
 filesystem.streamText=async(target:any,...args:any[])=>{reads.push(target);return originalStream(target,...args)}
 filesystem.stat=async(target:any,...args:any[])=>{if(fail.has(filesystem.processPath(target)))throw Error('controlled unavailable');return originalStat(target,...args)}
 const resolved={...config.resolveConfig({maxBytes:65536,maxSourceBytes:128}),dshHome:home,agentsHome:shared,localInstructionFileCandidates:[]},options={cwd:project,projectRoot:project,authorityMessages:[],scopeMessages:[],touchedPaths:[join(nested,'file.txt')],includeBaselineScopes:true,signal:fixture.signal}
 const clean=(value:any):any=>value instanceof Map?Object.fromEntries([...value].map(([key,item])=>[key,clean(item)])):Array.isArray(value)?value.map(clean):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).filter(([key])=>key!=='id').map(([key,item])=>[key,key==='version'?'<opaque-version>':clean(item)])):value
 async function run(name:string,settings=resolved,opts:any={},commit=true){
  reads.length=0;const result=await state.reconcileInstructionContext(agent,settings,cache,filesystem,{...options,...opts})
  rows.push({name,result:clean(result??null),reads:reads.length,cache:clean(cache.get(agent.session)??new Map())})
  if(result&&commit){state.applyInstructionVersionUpdates(agent.session,result.versionUpdates,cache);agent.session.append('user/message',result.context,{surfaceOp:'append'})}
  return result
 }
 await run('initial');await run('warm')
 write(join(project,'AGENTS.md'),' second ');await run('deduplicate-visible');await run('hidden-duplicate-fast-path')
 unlinkSync(join(project,'AGENTS.md'));await run('promote-hidden-sibling')
 write(join(project,'CLAUDE.md'),'second');await run('same-digest-new-version')
 write(join(project,'AGENTS.md'),'recreated first');write(join(project,'CLAUDE.md'),'x'.repeat(129));write(join(home,'AGENTS.md'),'global independently changed');await run('oversized-group-rollback')
 write(join(project,'CLAUDE.md'),'second recovered');fail.add(join(project,'CLAUDE.md'));await run('unavailable-group-rollback');fail.clear();await run('recovered-group')
 await run('excluded-baseline',resolved,{excludedBaselineScopes:new Set(['.\0AGENTS.md'])})
 const claimed=message('claimed',[{action:'remove',scope:'pkg\0AGENTS.md',path:join('pkg','AGENTS.md')}]);await run('claimed-overrides-surface',resolved,{authorityMessages:[claimed],includeBaselineScopes:false})
 write(join(nested,'CLAUDE.md'),'new hinted sibling');const hint=message('pending',[{action:'set',scope:'pkg\0CLAUDE.md',path:join('pkg','CLAUDE.md')}]);await run('pending-scope-hint',resolved,{scopeMessages:[hint],touchedPaths:[],includeBaselineScopes:false})
 write(join(nested,'AGENTS.md'),'new content to retry after tiny rendering budget');await run('notice-only-budget',{...resolved,maxBytes:3},{},false);await run('retry-after-budget')
 rows.push({name:'baseline-state',value:clean(state.baselineInstructionState([{absolutePath:'one',displayPath:'AGENTS.md',content:'\ufeff😀value\x1c'},{absolutePath:'two',displayPath:join('pkg','AGENTS.md'),content:' nested ',version:'known'}]))})
 const change={action:'remove',scope:'x',path:'x'},updates=[{change},{change:{...change,action:'set',digest:'a'}}];rows.push({name:'retained-updates',value:state.retainedInstructionVersionUpdates(updates,[{...change,ignored:true}])})
}finally{if(handle)await handle.dispose();await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
