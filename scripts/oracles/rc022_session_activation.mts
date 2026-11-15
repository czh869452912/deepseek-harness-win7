import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),fixture=await setup(join(workspace,'source')),ctx=fixture.ctx,rows:any[]=[],requests:any[]=[]
const {ApiSessionAgentController}=await load('packages/api/session-controller/src/agent.ts'),{SessionCommandController}=await load('packages/api/session-controller/src/commands.ts')
const {MockAdapter,textResponse}=await load('packages/core/agent-loop/tests/mock-adapter.ts'),{createUserMessage}=await load('packages/llm/llm/src/index.ts')
let defaults:any={provider:'record',model:'initial'},enterSave!:()=>void,releaseSave!:()=>void
const saveEntered=new Promise<void>(r=>enterSave=r),released=new Promise<void>(r=>releaseSave=r)
let savePending=true
class Recording extends MockAdapter{
 override async listModels(provider:string){return ['initial','changed','selected'].map(id=>({provider,id,name:id}))}
 override async *stream(request:any){requests.push({provider:request.provider,model:request.model});yield* textResponse('done')}
}
try{
 await ctx.plugin((await load('packages/typert/registry/src/index.ts')).default)
 ctx.baseUrl=pathToFileURL(workspace).href+'/'
 await ctx.plugin((await load('vendor/loader/src/index.ts')).default)
 await ctx.plugin((await load('packages/preset/agent-preset-registry/src/index.ts')).default,{default:'coding'})
 for(const id of ['coding','reviewing'])await ctx.agentPresets.register({id,plugins:[]})
 ctx.provide('agentDefaultModel',{currentSelection:()=>({...defaults}),saveSelection:async(value:any)=>{enterSave();await released;defaults={...value}}})
 ctx.llm.registerAdapter(['record'],new Recording([]))
 const archived:string[]=[],members=['blank'],attached:string[]=[],entity={id:'work',path:join(workspace,'project'),sessionIds:members,attachSession:async(id:string)=>{attached.push(id);if(!members.includes(id))members.push(id)}}
 ctx.provide('workspaceRegistry',{get:(id:string)=>id==='work'?entity:undefined,archivedSessionIds:archived})
 const agents=new ApiSessionAgentController(ctx);agents.initialize()
 const commands=new SessionCommandController(ctx,agents,entity.path);await commands.initialize()
 const create=async(name:string,extra:any={})=>{const result=await commands.create({sessionId:name,...extra});return [result,ctx.agents.get(result.sessionId)] as const}
 const [first,blank]=await create('blank',{workspaceId:'work'})
 rows.push({name:'fresh',named:blank.id==='blank',preset:first.agentPreset,model:blank.model.current()})
 defaults.model='changed';rows.push({name:'dynamic-default',model:blank.model.current()})
 const [switched,same]=await create('blank',{workspaceId:'work',agentPreset:'reviewing'})
 rows.push({name:'reuse-select',same:same===blank,preset:switched.agentPreset,selections:blank.session.snapshotEvents().filter((e:any)=>e.type==='agent-preset/selected').map((e:any)=>e.data.agentPreset)})
 const selected=await Promise.all([create('blank',{workspaceId:'work',agentPreset:'coding'}),create('blank',{workspaceId:'work',agentPreset:'reviewing'})])
 rows.push({name:'ordered-claims',same:selected.every(([,agent])=>agent===blank),presets:selected.map(([result])=>result.agentPreset),final:ctx.agentPresets.presetForSession(blank.session)})
 const [omitted,reused]=await create('blank',{workspaceId:'work'});rows.push({name:'omitted-default',same:reused===blank,preset:omitted.agentPreset})
 for(const [name,request] of [['cwd-before-preset',{cwd:join(workspace,'wrong'),agentPreset:'missing'}],['missing-preset',{agentPreset:'missing'}],['missing-workspace',{workspaceId:'missing'}],['both-locations',{workspaceId:'work',cwd:entity.path}]] as const){try{await commands.create({sessionId:'blank',...request})}catch(error:any){rows.push({name,code:error.code})}}
 await commands.selectModel({sessionId:'blank',provider:'record',model:'selected'});await saveEntered
 const before=blank.session.seq;await commands.selectModel({sessionId:'blank',provider:'record',model:'selected'})
 rows.push({name:'selected-before-save',savePending,duplicateSkipped:blank.session.seq===before,current:blank.model.current(),projection:ctx.sessionProjections.snapshot(blank.session).values.modelSelection})
 try{await commands.selectModel({sessionId:'blank',provider:'record',model:'absent'})}catch(error:any){rows.push({name:'unavailable-model',code:error.code,current:blank.model.current()})}
 blank.followup(createUserMessage({content:[{type:'text',text:'task'}],source:{kind:'user'}}));await blank.whenIdle()
 rows.push({name:'actual-request',requests,projection:ctx.sessionProjections.snapshot(blank.session).values.modelSelection})
 const [started,replacement]=await create('blank',{workspaceId:'work'});rows.push({name:'started-mints',minted:replacement.id!=='blank',attached:attached.at(-1)===replacement.id,preset:started.agentPreset})
 archived.push(replacement.id);const [,unarchived]=await create(replacement.id,{workspaceId:'work'});rows.push({name:'archived-mints',minted:unarchived.id!==replacement.id})
 const [,outsider]=await create('outsider'),[,placed]=await create('outsider',{workspaceId:'work'});rows.push({name:'placement-mints',minted:placed!==outsider})
 const composition=await agents.composeAgent('reviewing'),cold=await ctx.agents.create({sessionId:'cold',meta:{cwd:entity.path,agentPreset:'reviewing'},agentOptions:{provider:'record',model:'initial'},setup:composition.setup});await cold.dispose()
 const [result,resumed]=await create('cold',{agentPreset:'coding'});rows.push({name:'cold-blank-reuse',named:resumed.id==='cold',preset:result.agentPreset,selections:resumed.session.snapshotEvents().filter((e:any)=>e.type==='agent-preset/selected').map((e:any)=>e.data.agentPreset)})
 const coldStarted=await ctx.agents.create({sessionId:'cold-started',meta:{cwd:entity.path},agentOptions:{provider:'record',model:'initial'}});coldStarted.agent.session.append('turn/start',{turn:1});await coldStarted.dispose()
 const [,fresh]=await create('cold-started');rows.push({name:'cold-started-mints',minted:fresh.id!=='cold-started',oldAgentAbsent:ctx.agents.get('cold-started')===undefined})
 await ctx.agents.create({sessionId:'child',meta:{cwd:entity.path,origin:'subagent'},agentOptions:{provider:'record',model:'initial'}})
 try{await create('child',{agentPreset:'missing'})}catch(error:any){rows.push({name:'child-before-preset',code:error.code})}
 savePending=false;releaseSave();await released;await Promise.resolve()
 rows.push({name:'settled',claims:0,saves:0,default:defaults})
}finally{releaseSave();await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))


