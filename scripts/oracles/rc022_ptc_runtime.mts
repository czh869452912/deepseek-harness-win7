import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Runtime}=await load('packages/ptc-runtime/ptc-runtime-node/src/index.ts')
const ctx=new Context(),data=JSON.parse(readFileSync(process.argv[3]!, 'utf8')),rows:any[]=[]
for(const path of ['packages/core/session/src/index.ts','packages/fs/fs-local/src/index.ts','packages/subprocess/subprocess-local/src/index.ts','packages/sandbox/sandbox-local/src/index.ts','packages/session/session-projection/src/index.ts']){const {default:Plugin}=await load(path);await ctx.plugin(Plugin,{})}
const {default:Policy}=await load('packages/sandbox/sandbox-policy/src/index.ts');await ctx.plugin(Policy,{mode:'danger-full-access',workspaceRoot:data.workspace})
await ctx.plugin(Runtime,{timeoutMs:5000,maxTimeoutMs:7000,maxOutputBytes:4096})
const runtime=ctx.ptcRuntime,bindings=[{global:'tools',functions:Object.assign(Object.create(null),{['__proto__']:async(args:any)=>({value:args.n*2}),fail:async()=>{throw new Error('binding refused')},large:async()=> 'x'.repeat(100000)}),errorClass:{name:'ToolCallError',memberNameProperty:'toolName'}}]
try{
 for(const requested of ['absent',null,1,10000,0,-1,true,'100',[]]){
  const request:any={program:'',bindings,cwd:data.workspace};if(requested!=='absent')request.timeoutMs=requested
  try{const spec=runtime.resolve(request);rows.push({kind:'resolve',value:spec.timeoutMs,bindingIdentity:spec.bindings===bindings})}catch{rows.push({kind:'resolve',rejected:true})}
 }
 for(const test of data.cases){const controller=new AbortController();if(test.name==='abort')controller.abort('stop');const spec=runtime.resolve({program:test.typescript,bindings,cwd:data.workspace,timeoutMs:test.name==='timeout'?250:5000,signal:controller.signal});let result=await runtime.run(spec);delete result.sandbox;if(result.error)result={error:result.error.kind};rows.push({kind:test.name,result})}
 const controller=new AbortController(),entered=Promise.withResolvers<void>(),settled=Promise.withResolvers<void>(),release=Promise.withResolvers<void>()
 const pending=runtime.run(runtime.resolve({program:'return await tools.slow({})',bindings:[{global:'tools',functions:{slow:async()=>{entered.resolve();await release.promise;settled.resolve();return 'done'}}}],cwd:data.workspace,signal:controller.signal}));await entered.promise;controller.abort('stop');const result=await pending;let completed=false;void settled.promise.then(()=>{completed=true});rows.push({kind:'binding-abort',error:result.error.kind,callerOwned:!completed});release.resolve();await settled.promise
 const active=runtime.run(runtime.resolve({program:'while(true){}',bindings:[],cwd:data.workspace}));await new Promise(r=>setTimeout(r,30));await ctx.fiber.dispose();rows.push({kind:'dispose',error:(await active).error.kind})
 for(const method of ['resolve','run']){let rejected=false;try{await runtime[method]({program:'return 1',bindings:[],cwd:data.workspace,timeoutMs:5000})}catch{rejected=true}rows.push({kind:'late-'+method,rejected})}
 process.stdout.write(JSON.stringify(rows))
}finally{await ctx.fiber.dispose()}
