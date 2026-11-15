import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Runtime}=await load('packages/ptc-runtime/ptc-runtime-node/src/index.ts'),data=JSON.parse(readFileSync(process.argv[3]!, 'utf8')),ctx=new Context(),rows:any[]=[]
for(const path of ['packages/core/session/src/index.ts','packages/fs/fs-local/src/index.ts','packages/subprocess/subprocess-local/src/index.ts','packages/sandbox/sandbox-local/src/index.ts','packages/session/session-projection/src/index.ts']){const {default:Plugin}=await load(path);await ctx.plugin(Plugin,{})}
const {default:Policy}=await load('packages/sandbox/sandbox-policy/src/index.ts');await ctx.plugin(Policy,{mode:'danger-full-access',workspaceRoot:data.workspace});await ctx.plugin(Runtime,{timeoutMs:5000,maxOutputBytes:1024})
try{
 for(const test of data.cases){const result=await ctx.ptcRuntime.run(ctx.ptcRuntime.resolve({program:test.typescript,bindings:[],cwd:data.workspace}));rows.push({name:test.name,result:result.error?{error:result.error.kind}:{logs:result.logs.join(''),value:result.value??null}})}
 process.stdout.write(JSON.stringify(rows))
}finally{await ctx.fiber.dispose()}
