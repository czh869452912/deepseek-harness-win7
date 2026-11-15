import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const fixture=await setup(join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source')),ctx=fixture.ctx,rows:any[]=[],cases=JSON.parse(readFileSync(new URL('./rc022_persistent_protocol_cases.json',import.meta.url),'utf8'))
try{
 await ctx.plugin((await load('packages/terminal/terminal/src/index.ts')).default)
 const handle=await ctx.agents.create({sessionId:'protocol',agentOptions:{provider:'script',model:'model'}}),agent=handle.agent
 const provider=await load('packages/shell/tool-pwsh-persistent/src/index.ts')
 for(const [index,original] of cases.entries()){
  const entry=structuredClone(original),sessions:any[]=[],controller=new AbortController();let attempts=0
  class Session{
   motd='';pid=123;text='';closed=false;value:any={kind:'running'};steps=[...entry.steps];markers:any={}
   status(){return this.value}
   startSend(request:any){
    const step=this.steps.shift();if(step.error)throw new Error(step.error)
    if(request.text)this.markers={START:request.text.match(/__DSH_PERSISTENT_PWSH_START_[^_]+__/)![0],END:request.text.match(/__DSH_PERSISTENT_PWSH_END_[^:]+:/)![0],WRAPPER:request.text}
    let text=step.text;for(const key of ['WRAPPER','START','END'])text=text.replaceAll('$'+key,this.markers[key]);this.text+=text
    if(step.exit)this.value=step.exit
    const result={viewport:entry.incremental?'':text,waitReason:step.wait??'stdin_read',sessionStatus:this.value,truncated:false}
    const done=step.onAbort?new Promise(resolve=>{request.signal.addEventListener('abort',()=>resolve(result),{once:true});if(entry.cancel)queueMicrotask(()=>controller.abort(new Error('caller cancelled')))}):Promise.resolve(result)
    if(step.afterExit)this.value=step.afterExit
    return {done,readOutput:()=>({delta:entry.incremental?text:'',truncated:false}),cancel:()=>false}
   }
   read(request:any){
    if(entry.emptyRead)return {text:'',totalLines:0,lineBegin:0,lineEnd:0,truncated:false}
    const lines=this.text.split('\n'),offset=request.offset??0,end=lines.length-offset,begin=Math.max(0,end-(entry.pageLines??lines.length))
    return {text:lines.slice(begin,end).join('\n'),totalLines:lines.length,lineBegin:offset,lineEnd:offset+end-begin,truncated:entry.historyTruncated??false}
   }
   async close(){this.closed=true}
  }
  ctx.terminals.registerBackend({type:'stub-'+index,spawn:async()=>{attempts++;if(entry.spawnFailure&&attempts===1)throw new Error('spawn failed');const session=new Session();sessions.push(session);return session}})
  const plugin=await ctx.plugin(provider,{backendType:'stub-'+index,timeoutMs:entry.timeout??1000,maxOutputChars:entry.maximum??16000})
  const call=async()=>{try{return {value:await ctx.tools.get('pwsh').execute({command:'fixture'},{agent,signal:controller.signal})}}catch(error){return {error:(error as Error).message}}}
  const row:any={name:entry.name,result:await call()};if(entry.retry){entry.steps=[{text:'$START\nrecovered\n$END0\n'}];row.retry=await call()}
  row.retainedBeforeUnload=ctx.terminals.list(agent).length;await plugin.dispose();Object.assign(row,{allocations:sessions.length,closed:sessions.every(session=>session.closed),retained:ctx.terminals.list(agent).length});rows.push(row)
 }
 await handle.dispose()
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
