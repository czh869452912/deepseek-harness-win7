import {PassThrough} from 'node:stream'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{TerminalController}=await load('packages/api/terminal-controller/src/index.ts'),rows:any[]=[]
const signal=()=>new AbortController().signal,request={id:'one',cols:20,rows:4}
function fixture(){
 const ctx=new Context(),calls:any[]=[],handles:any[]=[]
 const provider:any={gate:null,abort:null,platform:'posix',default:'/bin/bash',
  async terminalEnvironment(signal:any){signal.throwIfAborted();return {platform:this.platform,defaultShell:this.default}},
  async resolveExecutable(path:string,_env:any,signal:any){signal.throwIfAborted();return path},
  async spawnTerminal(spec:any){
   const {signal:_signal,...rest}=spec;calls.push(['spawn',rest]);const output=new PassThrough(),done=Promise.withResolvers<any>()
   const handle:any={pid:123,output,done:done.promise,terminated:0,failures:0,
    async write(data:string){calls.push(['write',data])},async resize(cols:number,rows:number){calls.push(['resize',cols,rows])},
    async inspectActivity(){return {state:'unknown',revision:0}},async inspectForeground(){return undefined},async signalForeground(){return 123},
    async terminate(){this.terminated++;if(this.failures){this.failures--;throw Error('cleanup failure')}output.end();done.resolve({exitCode:0,signal:null})}}
   handles.push(handle);if(this.gate)await this.gate.promise;if(this.abort)this.abort.abort(Error('allocation cancelled'));return handle
  },spawn(spec:any){calls.push(['ordinary',spec]);return {done:Promise.resolve({exitCode:0,signal:null})}}}
 const directory={get:(session:any)=>session.header.cwd??'/workspace',async ensure(agent:any,signal:any){signal.throwIfAborted();return this.get(agent.session)}}
 ctx.provide('subprocess',provider);ctx.provide('sandboxPolicy',{defaultMode:'danger-full-access'});ctx.provide('workingDirectory',directory)
 const controller=new TerminalController(ctx,{shellCandidates:['bash','sh'],maxTerminals:2,maxAgentTerminals:1,maxCols:500,maxRows:200,scrollback:1000,maxBufferedBytes:2097152,maxInputBytes:65536,disposeGraceMs:1000,unattendedTimeoutMs:0,activityPollIntervalMs:30000,cleanupRetryMs:60000}),agent={id:'session',ctx,session:{id:'session',header:{} as any}}
 return {ctx,controller,agent,provider,handles,calls}
}
async function error(operation:()=>any){try{return {value:await operation()}}catch(failure:any){return {error:failure.message,code:failure.code??null,name:failure.name}}}
function record(name:string,controller:any,calls:any,handles:any[],extra:any=null){rows.push(structuredClone({name,roster:controller.list('session'),calls,terminations:handles.map(h=>h.terminated),extra}))}
{
 const {ctx,controller,agent,provider,handles,calls}=fixture()
 try{
  rows.push({name:'environment',value:controller.environment(agent,signal())})
  const first=await controller.create(agent,request,signal());agent.session.header.cwd='/changed';provider.default='/bin/sh'
  const same=await controller.create(agent,request,signal());record('idempotent',controller,calls,handles,{same:same===first})
  await controller.create(agent,{...request,id:'two'},signal());record('directory',controller,calls,handles)
  rows.push({name:'capacity',result:await error(()=>controller.create(agent,{...request,id:'three'},signal()))})
  await controller.close(agent,'one');rows.push({name:'closed-id',result:await error(()=>controller.create(agent,request,signal()))})
  await controller.close(agent,'one');await controller.close(agent,'two');record('removed',controller,calls,handles)
  for(const bad of ['','bad.id','中','x'.repeat(129)])rows.push({name:'bad-id',result:await error(()=>controller.create(agent,{...request,id:bad},signal()))})
  rows.push({name:'bad-size',result:await error(()=>controller.create(agent,{...request,id:'new',cols:true},signal()))})
 }finally{await ctx.fiber.dispose()}
}
{
 const {ctx,controller,agent,provider,handles,calls}=fixture()
 try{
  provider.gate=Promise.withResolvers();const first=controller.create(agent,request,signal());await Promise.resolve();await Promise.resolve()
  const second=controller.create(agent,request,signal());await Promise.resolve();const closing=controller.close(agent,'one');await Promise.resolve();provider.gate.resolve()
  const result=await Promise.allSettled([first,second,closing]);record('close-during-allocation',controller,calls,handles,result.map(value=>value.status==='rejected'?value.reason.message:null))
 }finally{await ctx.fiber.dispose()}
}
{
 const {ctx,controller,agent,provider,handles,calls}=fixture()
 try{
  const abort=new AbortController();provider.abort=abort
  const result=await error(()=>controller.create(agent,request,abort.signal));record('cancelled-allocation',controller,calls,handles,result)
  rows.push({name:'cancelled-id',result:await error(()=>controller.create(agent,request,signal()))})
 }finally{await ctx.fiber.dispose()}
}
{
 const {ctx,controller,agent,handles,calls}=fixture()
 try{
  await controller.create(agent,request,signal());handles[0].failures=1
  rows.push({name:'cleanup-failure',result:await error(()=>controller.close(agent,'one'))})
  record('retained-for-retry',controller,calls,handles);await controller.close(agent,'one');record('retry',controller,calls,handles)
 }finally{await ctx.fiber.dispose()}
}
{
 const {ctx,controller,agent,handles,calls}=fixture()
 try{
  ctx.provide('sandbox',{async confine(argv:any,policy:any,_signal:any){calls.push(['confine',argv,policy]);return {argv:['confined',...argv]}}})
  const requestAgent={title:'agent',cols:20,rows:4,preferredShells:['SH'],policy:{mode:'workspace-write',workspaceRoot:'/workspace'},env:{CUSTOM:'yes',DSH_SESSION_ID:'wrong',HISTFILE:'wrong'}}
  const launch=await controller.agentLaunch(agent,'fixed-agent',requestAgent,signal()),{release,...publicLaunch}=launch
  rows.push(structuredClone({name:'agent-launch',launch:publicLaunch,calls}));await release();record('history-cleanup',controller,calls,handles)
  const handle=await controller.openForAgent(agent,{...requestAgent,policy:{mode:'danger-full-access'}},signal())
  rows.push({name:'agent-handle',origin:handle.info.origin,control:handle.info.control,title:handle.info.title,pid:handle.pid})
  rows.push({name:'agent-capacity',result:await error(()=>controller.openForAgent(agent,requestAgent,signal()))});await handle.close()
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
