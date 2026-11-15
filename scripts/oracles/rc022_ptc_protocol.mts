import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
import {Duplex} from 'node:stream'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {createProcessRpc}=await load('packages/ptc-runtime/ptc-runtime-node/src/rpc.ts'),data=JSON.parse(readFileSync(process.argv[3]!, 'utf8')),rows:any[]=[]
const tick=()=>new Promise(r=>setImmediate(r))
for(const test of data.cases){
 const values:any[]=[],stream=new Duplex({read(){},write(_c,_e,done){done()}}),row:any={name:test.name,values,failure:null}
 const rpc=createProcessRpc(stream,test.maximum,{ping:(value:any)=>{values.push(value)}},[],(_error:any,kind:string)=>{row.failure??=kind})
 for(const chunk of test.chunks){stream.emit('data',Buffer.from(chunk));await tick()}
 if(test.eof)stream.emit('end')
 await tick();rows.push(row);rpc.$close()
}
for(const [maximum,count] of [[256,1],[256,4],[97,1],[96,1]]){
 const stream=new Duplex({read(){},write(_c,_e,_done){}}),row:any={name:'outgoing',maximum,count,admitted:0,failure:null}
 const rpc=createProcessRpc(stream,maximum,{},['notice'],(_error:any,kind:string)=>{row.failure??=kind})
 for(let n=0;n<count;n++){await rpc.notice('x'.repeat(64));if(row.failure)break;row.admitted++}
 rows.push(row);rpc.$close()
}
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Runtime}=await load('packages/ptc-runtime/ptc-runtime-node/src/index.ts')
for(const config of [{maxPendingCalls:1},{maxMessageBytes:512}]){
 const ctx=new Context(),release=Promise.withResolvers<void>(),settled=Promise.withResolvers<void>();let calls=0,completed=false
 for(const path of ['packages/core/session/src/index.ts','packages/fs/fs-local/src/index.ts','packages/subprocess/subprocess-local/src/index.ts','packages/sandbox/sandbox-local/src/index.ts','packages/session/session-projection/src/index.ts']){const {default:Plugin}=await load(path);await ctx.plugin(Plugin,{})}
 const {default:Policy}=await load('packages/sandbox/sandbox-policy/src/index.ts');await ctx.plugin(Policy,{mode:'danger-full-access',workspaceRoot:data.workspace});await ctx.plugin(Runtime,{timeoutMs:5000,...config})
 const runtime=ctx.ptcRuntime
 try{
  const result=await runtime.run(runtime.resolve({program:'const first=tools.slow("x".repeat(300));await new Promise(r=>setTimeout(r,50));await Promise.all([first,tools.slow("y".repeat(300))])',bindings:[{global:'tools',functions:{slow:async()=>{calls++;await release.promise;completed=true;settled.resolve();return null}}}],cwd:data.workspace}))
  rows.push({name:'pending',config,error:result.error?.kind??null,calls,callerOwned:!completed})
 }finally{release.resolve();if(calls)await settled.promise;await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
