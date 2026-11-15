import {readFileSync,mkdirSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const base=JSON.parse(readFileSync(process.argv[3]!,'utf8')),directory=join(base,'source-work');mkdirSync(join(directory,'moved'),{recursive:true})
const fixture=await setup(join(base,'source'),directory),ctx=fixture.ctx,rows:any[]=[],launches:string[]=[],sessions:any[]=[]
ctx.provide('subprocess',{spawnTerminal:async(spec:any)=>{launches.push(spec.cwd);throw new Error('measured-launch')}})
ctx.provide('sandboxPolicy',{resolve:()=>({mode:'danger-full-access',workspaceRoot:directory})})
try{
 await ctx.plugin((await load('packages/terminal/terminal/src/index.ts')).default)
 const local=await ctx.plugin(await load('packages/terminal/terminal-bash/src/index.ts'),{shellDialect:'pwsh'})
 const handle=await ctx.agents.create({sessionId:'terminal',meta:{cwd:directory},agentOptions:{provider:'script',model:'model'}}),agent=handle.agent
 for(const [name,request] of [['initial',{type:'shell'}],['changed',{type:'shell'}],['explicit',{type:'shell',cwd:directory}]] as const){if(name==='changed')await ctx.workingDirectory.set(agent,'moved',fixture.signal);try{await ctx.terminals.spawn(agent,request,fixture.signal)}catch(error){rows.push({name,error:(error as Error).message,cwd:launches.at(-1)})}}
 await local.dispose()
 class Session{
  motd='';pid=123;closed=false;text='';constructor(readonly cwd:string){}
  status(){return {kind:this.closed?'exited':'running'}}
  startSend(request:any){const start=request.text.match(/__DSH_PERSISTENT_PWSH_START_[^_]+__/)![0],end=request.text.match(/__DSH_PERSISTENT_PWSH_END_[^:]+:/)![0];this.text=start+'\n'+this.cwd+'\n'+end+'0\n';return {done:Promise.resolve({viewport:this.text,waitReason:'stdin_read',sessionStatus:this.status(),truncated:false}),readOutput:()=>({delta:this.text,truncated:false}),cancel:()=>false}}
  read(){return {text:this.text,totalLines:3,lineBegin:0,lineEnd:3,truncated:false}}
  async close(){this.closed=true}
 }
 ctx.terminals.registerBackend({type:'stub',spawn:async(spec:any)=>{const session=new Session(spec.cwd);sessions.push(session);return session}})
 const provider=await load('packages/shell/tool-pwsh-persistent/src/index.ts');let plugin=await ctx.plugin(provider,{backendType:'stub'})
 const run=()=>ctx.tools.get('pwsh').execute({command:'pwd'},{agent,signal:fixture.signal})
 rows.push({name:'persistent-first',value:await run(),allocations:sessions.length});await ctx.workingDirectory.set(agent,'..',fixture.signal)
 rows.push({name:'persistent-reused',value:await run(),allocations:sessions.length,current:ctx.workingDirectory.get(agent.session)})
 await plugin.dispose();rows.push({name:'persistent-unload',closed:sessions.every(session=>session.closed),retained:ctx.terminals.list(agent).length})
 plugin=await ctx.plugin(provider,{backendType:'stub'});rows.push({name:'persistent-recreated',value:await run(),allocations:sessions.length})
 await handle.dispose();await ctx.fiber.dispose();rows.push({name:'owner-unload',closed:sessions.every(session=>session.closed)})
}finally{await ctx.fiber.dispose()}
const normalize=(value:any):any=>typeof value==='string'&&value.includes(directory)?value.replaceAll(directory,'<work>').replaceAll('\\','/'):Array.isArray(value)?value.map(normalize):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)])):value
process.stdout.write(JSON.stringify(normalize(rows)))
