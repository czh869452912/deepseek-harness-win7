import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Runtime}=await load('packages/ptc-runtime/ptc-runtime-node/src/index.ts'),data=JSON.parse(readFileSync(process.argv[3]!, 'utf8')),ctx=new Context(),rows:any[]=[]
for(const path of ['packages/core/session/src/index.ts','packages/fs/fs-local/src/index.ts','packages/subprocess/subprocess-local/src/index.ts','packages/sandbox/sandbox-local/src/index.ts','packages/session/session-projection/src/index.ts']){const {default:Plugin}=await load(path);await ctx.plugin(Plugin,{})}
const {default:Policy}=await load('packages/sandbox/sandbox-policy/src/index.ts');await ctx.plugin(Policy,{mode:'read-only',workspaceRoot:data.workspace});await ctx.plugin(Runtime,{timeoutMs:5000})
const runtime=ctx.ptcRuntime,project=(r:any)=>r.error?{error:r.error.kind,sandbox:r.sandbox}:{value:r.value??null,sandbox:r.sandbox}
try{
 const bindings:any[]=[],spec=runtime.resolve({program:'',bindings});rows.push({name:'defaults',mode:spec.sandboxPolicy.mode,cwd:spec.cwd===data.workspace,timeout:spec.timeoutMs,bindingIdentity:spec.bindings===bindings})
 const other=runtime.resolve({program:'',bindings,timeoutMs:null,sandboxPolicy:null});rows.push({name:'null-defaults',mode:other.sandboxPolicy.mode,timeout:other.timeoutMs})
 for(const [name,mode,program] of [
  ['readonly','read-only','await (await import("node:fs/promises")).writeFile("inside","yes");return 42'],
  ['workspace','workspace-write','await (await import("node:fs/promises")).writeFile("inside","yes");return 42'],
  ['outside','workspace-write','await (await import("node:fs/promises")).writeFile("../outside","yes");return 42'],
  ['full','danger-full-access','return 42'],['environment','workspace-write','return {...process.env}'],['timeout','workspace-write','while(true){}']
 ]){rows.push({name,result:project(await runtime.run(runtime.resolve({program,bindings:[],timeoutMs:name==='timeout'?200:5000,sandboxPolicy:{mode,workspaceRoot:data.workspace}})))})}
 const session=ctx.sessions.create('policy-live'),entered=Promise.withResolvers<void>(),release=Promise.withResolvers<void>(),settled=Promise.withResolvers<void>();let completed=false
 const pending=runtime.run(runtime.resolve({program:'return await tools.slow({})',bindings:[{global:'tools',functions:{slow:async()=>{entered.resolve();await release.promise;completed=true;settled.resolve();return null}}}],sandboxPolicy:ctx.sandboxPolicy.resolve({session,mode:'workspace-write'})}));await entered.promise
 session.append('sandbox/mode',{mode:'workspace-write'});session.append('sandbox/mode',{mode:'danger-full-access'});const result=await pending;rows.push({name:'policy-abort',result:project(result),callerOwned:!completed});release.resolve();await settled.promise
 const active=runtime.run(runtime.resolve({program:'while(true){}',bindings:[],sandboxPolicy:{mode:'danger-full-access',workspaceRoot:data.workspace}}));await new Promise(r=>setTimeout(r,50));await ctx.fiber.dispose();rows.push({name:'dispose',result:project(await active)})
 process.stdout.write(JSON.stringify(rows))
}finally{await ctx.fiber.dispose()}
