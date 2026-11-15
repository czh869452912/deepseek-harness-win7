import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const run=await load('packages/subagent/subagent-dsh-sdk/src/run.ts'),errors=await load('packages/sdk/client/src/client.ts'),rows:any[]=[]
const original=run.internals.createHarness,names=['RC022_AMBIENT_TOKEN','DSH_RC022_FACT'],old=names.map(name=>process.env[name])
process.env.RC022_AMBIENT_TOKEN='ambient';process.env.DSH_RC022_FACT='ambient'
try{for(const input of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const trace:any[]=[],reports:any[]=[],options:any={},queue:any[]=[],controller=new AbortController(),closed=Promise.withResolvers<void>(),state:any={}
 if(input.kind==='pre-aborted')controller.abort()
 const rawError=(kind:string)=>kind==='protocol'?new errors.SdkProtocolError('private protocol'):kind==='transport'?new errors.TransportClosedError({code:17,signal:null},[]):Error('private failure')
 const publish=(event:any)=>{const note={method:'session.event',params:{sessionId:state.session,event}};if(state.filter(note))queue.push(note)}
 class Harness{
  client=this
  async start(){trace.push('start');if(input.kind.startsWith('cancel-start')){controller.abort();await closed.promise;return}if(input.kind.startsWith('startup')){const error=rawError('protocol');if(input.kind==='startup-aggregate')throw new AggregateError([error,Error('private cleanup')],'private aggregate');throw error}}
  session(id:string){state.session=id;return this}
  async setWorkingDirectory(cwd:string){trace.push(['cwd',cwd])}
  subscribe(predicate:any){state.filter=predicate;return {tryNext:()=>queue.shift(),close:()=>trace.push('unsubscribe')}}
  async prompt(id:string,prompt:any){trace.push(['prompt',prompt]);state.session=id;publish({type:'assistant/attempt',data:{stream:[{type:'text-chunks',time0:0,index:0,dt:[],texts:['partial']}]}})}
  async request(method:string,params:any){trace.push(method);if(['protocol','transport','unknown','sink-throws'].includes(input.kind))throw rawError(input.kind==='sink-throws'?'unknown':input.kind);if(input.kind==='cancel'){controller.abort();await closed.promise;return}if(input.kind==='malformed-event'){publish(1);return}if(input.kind==='malformed-reason'){publish({type:'turn/end',data:{reason:{kind:'aborted'}}});return}publish({type:'assistant/message',data:{message:{content:[{type:'text',text:'answer'}]},stream:[]}});if(input.reason!==undefined&&input.reason!==null)publish({type:'turn/end',data:{reason:input.reason}})}
  async close(){trace.push('close');closed.resolve();if(['shutdown','cancel-start-cleanup'].includes(input.kind))throw Error('private cleanup')}
 }
 run.internals.createHarness=(received:any)=>{Object.assign(options,received);return new Harness()}
 const spec={profile:'sdk',patches:['patch'],dshHome:'home',cwd:'child',originCwd:'origin',provider:'provider',model:'model',reasoningEffort:'low',maxTokens:12,env:{RC022_AMBIENT_TOKEN:'explicit'},shutdownTimeoutMs:1000,disposeEofGraceMs:6000,disposeGraceMs:3000,onError:(error:any,reason:any)=>{reports.push([error.name==='Error'?'RuntimeError':error.name,reason]);if(input.kind==='sink-throws')throw Error('sink failure')}}
 const failure=(error:any):any=>({name:error.name==='Error'?'RuntimeError':error.name,message:error.message,errors:error instanceof AggregateError?error.errors.map(failure):[]})
 let value:any
 try{const handle=await run.startSdkRun({signal:controller.signal,prompt:[{type:'text',text:'task'}]},spec),result=await handle.result,first=handle.dispose(),second=handle.dispose();let disposal:any=null;try{await first}catch(error){disposal=failure(error)}value={result,sameDisposal:first===second,disposal}}
 catch(error){value={startFailure:failure(error)}}
 rows.push({value,trace,reports,options:Object.fromEntries(['profile','patches','dshHome','processCwd','cwd','provider','model','reasoningEffort','maxTokens'].filter(key=>key in options).map(key=>[key,options[key]])),environment:Object.fromEntries(names.map(name=>[name,options.env?.[name]??null])),listeners:0})
 await Promise.resolve()
}}finally{run.internals.createHarness=original;names.forEach((name,i)=>{if(old[i]===undefined)delete process.env[name];else process.env[name]=old[i]})}
process.stdout.write(JSON.stringify(rows))
