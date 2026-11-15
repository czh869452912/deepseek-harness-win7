import {resolve,join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href),workspace=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source')
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Loop}=await load('packages/core/agent-loop/src/index.ts'),Backend=await load('packages/session/session-persistence-jsonl/src/index.ts')
const {SessionPersistenceNotFoundError}=await load('packages/session/session-persistence/src/index.ts')
const plugins=[]
for(const path of ['packages/llm/llm/src/index.ts','packages/core/session/src/index.ts','packages/session/session-projection/src/index.ts','packages/core/system-prompt/src/index.ts','packages/core/tools/src/index.ts','packages/core/tool-executor-native/src/index.ts','packages/core/agent/src/index.ts']){const module=await load(path);plugins.push(module.default??module)}
const rows:any[]=[]
for(const explicit of [false,true])for(const action of ['same','changed','explicit','partial','equal','fresh']){
 const ctx=new Context();for(const plugin of plugins)await ctx.plugin(plugin);await ctx.plugin(Backend,{root:join(workspace,String(explicit)+'-'+action),compression:'none'})
 const previous={provider:'p',model:'m',reasoningEffort:'high'},options:any={provider:'p',model:'m'}
 if(action==='changed')options.model='other';if(action==='explicit')options.reasoningEffort='low';if(action==='partial')delete options.provider;if(action==='equal')options.reasoningEffort='high'
 if(action!=='fresh'){const session=ctx.sessions.prepare('saved'),writer=await ctx.sessionPersistence.create(session.header);await writer.append([{type:'model/selection',seq:0,time:1,data:previous}]);await writer.close()}
 const row:any={action,explicit},created=Promise.withResolvers<void>()
 ctx.on('agent/created',()=>{row.published=ctx.agents.get('saved').model.current();created.resolve()})
 ctx.on('agent-loop/config-start-failed',(failure:any)=>created.reject(failure.error))
 try{
  const config={...options,id:'config',[explicit?'resumeSessionId':'sessionId']:'saved'};await ctx.plugin(Loop,{agents:[config]})
  if(explicit&&action==='fresh'){try{await created.promise}catch(error){if(!(error instanceof SessionPersistenceNotFoundError))throw error;row.error='not-found'}}
  else{await created.promise;row.events=ctx.agents.get('saved').session.snapshotEvents().filter((event:any)=>event.type==='model/selection').map((event:any)=>event.data)}
  rows.push(row)
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
